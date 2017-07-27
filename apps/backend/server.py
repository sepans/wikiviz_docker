#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2014 Radim Rehurek <me@radimrehurek.com>

"""
USAGE: %(program)s CONFIG

    Start the wiki-sim server for http://radimrehurek.com/2014/01/performance-shootout-of-nearest-neighbours-querying/#wikisim
and leave it running (ctrl+c to quit).

Ports/interfaces for the server are specified in the config file.

Example:
    ./runserver.py hetzner.conf

"""

from __future__ import with_statement

import os
import sys
from functools import wraps
import time
import logging
import json
import collections

import cherrypy
import cherrypy_cors
from cherrypy.process.plugins import DropPrivileges, PIDFile
import annoy
import gensim

import sqlite3


#fp=open('memory_profiler.log','w+')


logger = logging.getLogger(__name__)


def server_exception_wrap(func):
    """
    Method decorator to return nicer JSON responses: handle internal server errors & request timings.

    """
    @wraps(func)
    def _wrapper(self, *args, **kwargs):
        try:
            # append "success=1" and time taken in milliseconds to the response, on success
            logger.debug("calling server method '%s'" % (func.func_name))
            cherrypy.response.timeout = 3600 * 24 * 7  # [s]

            # include json data in kwargs; HACK: should be a separate decorator really, but whatever
            if getattr(cherrypy.request, 'json', None):
                kwargs.update(cherrypy.request.json)

            start = time.time()
            result = func(self, *args, **kwargs)
            if result is None:
                result = {}
            result['success'] = 1
            result['taken'] = time.time() - start
            logger.info("method '%s' succeeded in %ss" % (func.func_name, result['taken']))
            return result
        except Exception, e:
            logger.exception("exception serving request")
            result = {
                'error': repr(e),
                'success': 0,
            }
            cherrypy.response.status = 500
            return result
    return _wrapper


class Server(object):
    def __init__(self, basedir, k):
        self.basedir = basedir
        self.k = k
        #logger.info('loading index %s' %os.path.join(basedir, 'index4278026_annoy_100'))
        self.index_annoy = annoy.AnnoyIndex(500, metric='angular')
        self.index_annoy.load(os.path.join(basedir, 'index4278026_annoy_100'))

        # conn = sqlite3.connect('annoy.db')
        # self.c = conn.cursor()

        #self.id2title = gensim.utils.unpickle(os.path.join(basedir, 'id2title'))
        #logger.info('number of articles in index %s' %len(self.id2title))
        logger.info("loading wikiids")
        wikiidlist = gensim.utils.unpickle(os.path.join(basedir, 'wikiidlist'))
        #self.wikiids = wikiid2title.keys()
        #self.wikiIdToIndexId = collections.OrderedDict((int(wikiid), pos) for pos, wikiid in enumerate(self.wikiids))
        wikiIdToIndexId = collections.OrderedDict((int(wikiid), pos) for pos, wikiid in enumerate(wikiidlist))
        #print(wikiid2title['12'])
        #logger.info("first 5 titles in id2title %s " % self.id2title[0:20])
        #logger.info("first 5 wiki ids to index ids %s" % self.wikiIdToIndexId.items()[0:20])
        #logger.info("first 5 wiki ids %s" % self.wikiidlist[0:20])
        #logger.info("first 5 wiki values %s" % wikiid2title.values()[0:20])
        #self.title2id = dict((gensim.utils.to_unicode(title).lower(), pos) for pos, title in enumerate(self.id2title))
        with open(os.path.dirname(os.path.abspath(__file__)) + '/rasteredxx.json') as withidsfile:
            self.withids = json.load(withidsfile)
            for i in range(0, 10):
                key = list(self.withids.keys())[i]
                logger.info(" first key %s " % key)
                #print(wikiIdToIndexId.get(int(key), -1))
            hundredKIds = map( lambda d: wikiIdToIndexId.get(int(d), -1), list(self.withids.keys()))
        # print('kex '+self.hundredKIds[0]+' ')
        #del wikiIdToIndexId
        logger.info("hundredKIds %s " % hundredKIds[0:5])
        hundredKIds.sort()
        self.hundredKIdsSet = set(hundredKIds)
        logger.info("set built")
    
    def getXCoord(self, d):
	return d["x"]

    def getYCoord(self, d):
	return d["y"]
    
    def findMatchingSet(self, query, qSize):
        nn = self.index_annoy.get_nns_by_item(query, qSize)
        #nnwikiids = [int(self.wikiidlist[n]) for n in nn]
        logger.info("nn " % nn)
        #logger.info("nnwikiids " % nnwikiids)
        #intersection = set(nnwikiids) & self.hundredKIdsSet
        intersection2 = [x for x in nn if x in self.hundredKIdsSet]
        #print(intersection)
        print(intersection2)
        return intersection2
        
    def middlePosition(self, query, intersection, c): 
        print(query)
        print(intersection)
        intersection = intersection[:3]
        c.execute('SELECT wikiid FROM annoy_map WHERE annoy_id in (%s)' % ','.join('?'*len(intersection)), intersection)
        qresults = c.fetchall()
        result = [titleTuple[0] for titleTuple in qresults]  # convert top10 from ids back to article names

        x = [float(self.getXCoord(self.withids[str(p)])) for p in result]
        y = [float(self.getYCoord(self.withids[str(p)])) for p in result]
        print(x)
        print(y)
        centroid = [sum(x) / len(intersection), sum(y) / len(intersection)]
        print(centroid)
        return centroid
        #for item in intersection:
        #    stringItem = str(item)
        #    print(stringItem)
        #    itemInfo = self.withids[stringItem]
        #    print(itemInfo)

    @server_exception_wrap
    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def similars(self, *args, **kwargs):
        """
        For a Wiki article named `title`, return the top-k most similar Wikipedia articles.

        """
        title = gensim.utils.to_unicode(kwargs.pop('title', u'')).lower()
        useRastered = kwargs.pop('rastered', u'')
        logger.info("finding similars for %s" % title)

        conn = sqlite3.connect('annoy.db')
        c = conn.cursor()

        c.execute('SELECT annoy_id FROM annoy_map WHERE title = ?', (title,))
        qresult = c.fetchone()
        midPoint = []
        if qresult:#title in self.title2id:
            query = qresult[0]
            logger.info('query annoy id %s' % query)
            #query = self.title2id[title]  # convert query from article name (string) to index id (int)
            logger.info("query %s" % query)

            sqlq = (query,)
            c.execute('SELECT wiki_id FROM annoy_map WHERE annoy_id = ?', sqlq)
            qresults = c.fetchone()

            queryWikiid = qresults[0]#self.wikiidlist[query]
            logger.info("wikiids %s" % queryWikiid)
            logger.info("in query not converted? %s " % (query in self.hundredKIdsSet))
            logger.info("in? %s " % (queryWikiid in self.hundredKIdsSet))
            logger.info("in? str %s " % (str(queryWikiid) in self.hundredKIdsSet))
            logger.info("in? int %s " % (int(queryWikiid) in self.hundredKIdsSet))
            if query in self.hundredKIdsSet:
                logger.info(self.withids[str(queryWikiid)])
                midPoint = [self.getXCoord(self.withids[str(queryWikiid)]), self.getYCoord(self.withids[str(queryWikiid)])]
            else:
                qSize = 100
                intersection = self.findMatchingSet(query, qSize)
                while len(intersection)<3 and qSize < 200:
                    qSize = qSize + 100
                    intersection = self.findMatchingSet(query, qSize)
                logger.info("found 3 matches within %s neigbors" % qSize) 
                logger.info("neighbors ids %s" % intersection)
                #logger.info("neighbors %s" % [self.id2title[pos2] for pos2 in intersection])
                midPoint = self.middlePosition(query, intersection, c)
            nn = self.index_annoy.get_nns_by_item(query, 20)
            c.execute('SELECT title FROM annoy_map WHERE annoy_id in (%s)' % ','.join('?'*len(nn)), nn)
            qresults = c.fetchall()
            result = [titleTuple[0] for titleTuple in qresults]  # convert top10 from ids back to article names
            #logger.info("similars to %s: %s" % (title, result))
        else:
            result = []
        return {'nn': result, 'location': midPoint}

    @server_exception_wrap
    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def status(self, *args, **kwargs):
        """
        Return the server status.

        """
        result = {
            'basedir': self.basedir,
            'k': self.k,
            'num_articles': 'many'
        }
        return result
    ping = status

    @cherrypy.expose
    def index(self):
	REACT_DIR = os.path.abspath(os.path.dirname(__file__))
	return open(os.path.join(REACT_DIR, u'index.html'))

#endclass Server


class Config(object):
    def __init__(self, **d):
        self.__dict__.update(d)

    def __getattr__(self, name):
        return None # unset config values will default to None

    def __getitem__(self, name):
        return self.__dict__[name]


if __name__ == '__main__':
    logging.basicConfig(format='%(asctime)s : %(levelname)s : %(module)s:%(lineno)d : %(funcName)s(%(threadName)s) : %(message)s')
    logging.root.setLevel(level=logging.DEBUG)
    logging.info("running %s" % ' '.join(sys.argv))

    program = os.path.basename(sys.argv[0])

    # check and process input arguments
    if len(sys.argv) < 2:
        print globals()['__doc__'] % locals()
        sys.exit(1)

    cherrypy_cors.install()

    conf_file = sys.argv[1]
    config_srv = Config(**cherrypy.lib.reprconf.Config(conf_file).get('global'))
    config = Config(**cherrypy.lib.reprconf.Config(conf_file).get('wiki_sim'))

    if config_srv.pid_file:
        PIDFile(cherrypy.engine, config_srv.pid_file).subscribe()
    if config_srv.run_user and config_srv.run_group:
        logging.info("dropping priviledges to %s:%s" % (config_srv.run_user, config_srv.run_group))
        DropPrivileges(cherrypy.engine, gid=config_srv.run_group, uid=config_srv.run_user).subscribe()
    logging.info("base directory %s" % config.BASE_DIR)
    cherrypy.quickstart(Server(config.BASE_DIR, config.TOPN), config=conf_file)

    logging.info("finished running %s" % program)
