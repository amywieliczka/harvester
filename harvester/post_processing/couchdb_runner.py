import os
import datetime
import time
import couchdb
from redis import Redis
from rq import Queue

from harvester.config import config

COUCHDB_VIEW = 'all_provider_docs/by_provider_name'


class CouchDBCollectionFilter(object):
    '''Class for selecting collections from the UCLDC couchdb data store.
    '''
    def __init__(self,
                 collection_key=None,
                 couchdb_obj=None,
                 url_couchdb=None,
                 couchdb_name=None,
                 couch_view=COUCHDB_VIEW,
                 ):
        if not collection_key:
            collection_key = '{}'
        if couchdb_obj is None:
            if not url_couchdb or not couchdb_name:
                raise ValueError('Need url and name to couch database')
            self._couchdb = couchdb.Server(url=url_couchdb)[couchdb_name]
        else:
            self._couchdb = couchdb_obj
        self._view = couch_view
        self._view_iter = self._couchdb.view(self._view, include_docs='true',
                                             key=collection_key)

    def __iter__(self):
        return self._view_iter.__iter__()

    def next(self):
        return self._view_iter.next()


class CouchDBWorker(object):
    '''A class that can run functions on sets of couchdb documents
    maybe become some sort of decorator?
    Documents are mutable, so if the function mutates the document, it will
    be picked up here.
    ????Add the "save" keyword argument to save the document to db???
    functions should have call signature of (doc, *args, **kwargs)
    '''
    def __init__(self):
        self._config = config()
        url_couchdb = self._config.DPLA.get("CouchDb", "URL")
        couchdb_name = self._config.DPLA.get("CouchDb", "ItemDatabase")
        username = self._config.DPLA.get("CouchDb", "Username")
        password = self._config.DPLA.get("CouchDb", "Password")
        url = url_couchdb.split("//")
        url_server = "{0}//{1}:{2}@{3}".format(url[0], username, password, url[1])
        self._couchdb = couchdb.Server(url_server)[couchdb_name]

    def run_by_list_of_doc_ids(self, doc_ids, func, *args, **kwargs):
        '''For a list of ids, harvest images'''
        results = []
        for doc_id in doc_ids:
            doc = self._couchdb[doc_id]
            results.append((doc_id, func(doc, *args, **kwargs)))
        return results

    def run_by_collection(self, collection_key, func, *args, **kwargs):
        '''If collection_key is none, trying to grab all of the images. (Not
        recommended)
        '''
        v = CouchDBCollectionFilter(couchdb_obj=self._couchdb,
                                    collection_key=collection_key)
        results = []
        for r in v:
            dt_start = dt_end = datetime.datetime.now()
            result = func(r.doc, *args, **kwargs)
            results.append((r.doc['_id'], result))
            dt_end = datetime.datetime.now()
            time.sleep((dt_end-dt_start).total_seconds())
        return results


class CouchDBJobEnqueue(object):
    '''A class that will put a job on the RQ worker queue for each document
    selected. This should allow some parallelism.
    Functions passed to this enqueuing object should take a CouchDB doc id
    and should do whatever work & saving it needs to do on it.
    '''
    def __init__(self):
        self._config = config()
        url_couchdb = self._config.DPLA.get("CouchDb", "URL")
        couchdb_name = self._config.DPLA.get("CouchDb", "ItemDatabase")
        username = self._config.DPLA.get("CouchDb", "Username")
        password = self._config.DPLA.get("CouchDb", "Password")
        url = url_couchdb.split("//")
        url_server = "{0}//{1}:{2}@{3}".format(url[0], username, password, url[1])
        self._couchdb = couchdb.Server(url_server)[couchdb_name]
        self._redis = Redis(host=self._config.redis_host,
                            port=self._config.redis_port,
                            password=self._config.redis_pswd,
                            socket_connect_timeout=self._config.redis_timeout)
        self._rQ = Queue(connection=self._redis)

    def queue_collection(self, collection_key, job_timeout, func,
                         *args, **kwargs):
        '''Queue a job in the RQ queue for each document in the collection.
        func is function to run and it must be accessible from the
        rq worker's virtualenv.
        func signature is func(doc_id, args, kwargs)
        Can't pass the document in because it all gets converted to a string
        and put into the RQ queue. Much easier to pass id and have worker deal
        with couchdb directly.
        '''
        v = CouchDBCollectionFilter(couchdb_obj=self._couchdb,
                                    collection_key=collection_key)
        results = []
        for r in v:
            doc = r.doc
            this_args = [doc['_id']]
            if args:
                this_args.extend(args)
            this_args = tuple(this_args)
            print('Enqueing doc {} args: {} kwargs:{}'.format(doc['_id'],
                this_args, kwargs))
            result = self._rQ.enqueue_call(func=func,
                                     args=this_args,
                                     kwargs=kwargs,
                                     timeout=job_timeout)
            results.append(result)
        return results