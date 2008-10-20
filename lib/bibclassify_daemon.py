# -*- coding: utf-8 -*-
##
## This file is part of CDS Invenio.
## Copyright (C) 2002, 2003, 2004, 2005, 2006, 2007 CERN.
##
## CDS Invenio is free software; you can redistribute it and/or
## modify it under the terms of the GNU General Public License as
## published by the Free Software Foundation; either version 2 of the
## License, or (at your option) any later version.
##
## CDS Invenio is distributed in the hope that it will be useful, but
## WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
## General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with CDS Invenio; if not, write to the Free Software Foundation, Inc.,
## 59 Temple Place, Suite 330, Boston, MA 02111-1307, USA.

"""
BibClassify daemon.

FIXME: the code below requires collection table to be updated to add column:
   clsMETHOD_fk mediumint(9) unsigned NOT NULL,
This is not clean and should be fixed.
"""

import sys
import time
import os

from invenio.dbquery import run_sql
from invenio.bibtask import task_init, write_message, get_datetime, \
    task_set_option, task_get_option, task_update_status, \
    task_update_progress
from invenio.bibclassify_engine import get_keywords_from_text
from invenio.config import CFG_BINDIR, CFG_ETCDIR, CFG_TMPDIR, CFG_PATH_PDFTOTEXT
from invenio.intbitset import intbitset
from invenio.search_engine import get_collection_reclist
from invenio.bibdocfile import BibRecDocs

def get_recids_foreach_ontology():
    """Returns an array containing hash objects containing the collection, its
    corresponding ontology and the records belonging to the given collection."""

    rec_onts = []
    res = run_sql("""SELECT clsMETHOD.name, last_updated, collection.name
        FROM clsMETHOD JOIN collection_clsMETHOD ON clsMETHOD.id=id_clsMETHOD
        JOIN collection ON id_collection=collection.id""")
    for ontology, date_last_run, collection in res:
        recs = get_collection_reclist(collection)
        if recs:
            if not date_last_run:
                date_last_run = '0000-00-00'
            modified_records = intbitset(run_sql("SELECT id FROM bibrec WHERE modification_date >=%s", (date_last_run, )))
            recs &= modified_records
            if recs:
                rec_onts.append({
                    'ontology' : ontology,
                    'collection' : collection,
                    'recIDs' : recs
                })
    return rec_onts

def update_date_of_last_run():
    """
    Update bibclassify daemon table information about last run time.
    """
    run_sql("UPDATE clsMETHOD SET last_updated=NOW()")

def task_run_core():
    """Runs anayse_documents for each ontology,collection,record ids set."""
    outfilename = CFG_TMPDIR + "/bibclassifyd_%s.xml" % time.strftime("%Y%m%dH%M%S", time.localtime())
    outfiledesc = open(outfilename, "w")
    coll_counter = 0
    print >> outfiledesc, """<?xml version="1.0" encoding="UTF-8"?>"""
    print >> outfiledesc, """<collection xmlns="http://www.loc.gov/MARC21/slim">"""
    for onto_rec in get_recids_foreach_ontology():
        write_message('Applying taxonomy %s to collection %s (%s records)' % (onto_rec['ontology'], onto_rec['collection'], len(onto_rec['recIDs'])))
        if onto_rec['recIDs']:
            coll_counter += analyse_documents(onto_rec['recIDs'], onto_rec['ontology'], onto_rec['collection'], outfilename, outfiledesc)
    print >> outfiledesc, '</collection>'
    outfiledesc.close()
    if coll_counter:
        cmd = "%s/bibupload -n -c '%s' " % (CFG_BINDIR, outfilename)
        errcode = 0
        try:
            errcode = os.system(cmd)
        except OSError, exc:
            print 'command' + cmd + ' failed  ', exc
        if errcode != 0:
            write_message("WARNING, %s failed, error code is %s" % (cmd, errcode))
            return 0
    update_date_of_last_run()
    return 1

def analyse_documents(recs, ontology, collection, outfilename, outfiledesc):
    """For each collection, parse the documents attached to the records in collection with the corresponding ontology."""

    time_now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    did_something = False
    counter = 1
    amax = len(recs)
    # store running time:
    # see which records we'll have to process:
    #recIDs = get_recIDs_of_modified_records_since_last_run()
    temp_text = None
    if recs:
        # process records:
        cmd = None
        path = None
        temp_text = CFG_TMPDIR + '/bibclassify.pdftotext.' + str(os.getpid())
        for rec in recs:
            bibdocfiles = BibRecDocs(rec).list_latest_files()
            found_one_pdf = False
            for bibdocfile in bibdocfiles:
                if bibdocfile.get_format() == '.pdf':
                    found_one_pdf = True
            if found_one_pdf:
                did_something = True
                print >> outfiledesc, '<record>'
                print >> outfiledesc, """<controlfield tag="001">%(recID)s</controlfield>""" % ({'recID':rec})
                for f in bibdocfiles:
                    if f.get_format() == '.pdf':

                        cmd = "%s '%s' '%s'" % (CFG_PATH_PDFTOTEXT, f.get_full_path(), temp_text)
                    else:
                        write_message("Can't parse file %s." % f.get_full_path(), verbose=3)
                        continue
                    errcode = os.system(cmd)
                    if errcode != 0 or not os.path.exists("%s" % temp_text):
                        write_message("Error while executing command %s Error code was: %s " % (cmd, errcode))
                    write_message('Generating keywords for %s' % f.get_full_path())

def get_keywords_from_text(text_lines, output_mode="text",
    output_limit=CFG_BIBCLASSIFY_DEFAULT_OUTPUT_NUMBER, spires=False,
    match_mode="full", no_cache=False, with_author_keywords=False):

                    print >> outfiledesc, get_keywords_from_text(temp_text, CFG_ETCDIR + '/bibclassify/' + ontology + '.rdf', 2, 70, 25, 0, False, verbose=0, ontology=ontology)
                print >> outfiledesc, '</record>'
            task_update_progress("Done %s of %s for collection  %s." % (counter, amax, collection))
            counter += 1
    else:
        write_message("Nothing to be done, move along")
    return did_something

def cleanup_tmp():
    """Remove old temporary files created by this module"""
    for f in os.listdir(CFG_TMPDIR):
        if 'bibclassify' in f: os.remove(CFG_TMPDIR + '/' +f)

def main():
    """Constructs the bibclassifyd bibtask."""
    cleanup_tmp()
    task_init(authorization_action='runbibclassify',
              authorization_msg="BibClassify Task Submission",
              description="""Examples:
        %s -u admin
""" % (sys.argv[0],),
              version="",
              task_run_fnc = task_run_core)

if __name__ == '__main__':
    main()


# FIXME: one can have more than one ontologies in clsMETHOD.
#    bibclassifyd -w HEP,Pizza

# FIXME: add more CLI options like bibindex ones, e.g.
#    bibclassifyd -a -i 10-20

# FIXME: outfiledesc can be multiple files, e.g. when processing
#    100000 records it is good to store results by 1000 records
#    (see oaiharvest)
