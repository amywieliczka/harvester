import os
import sys
import datetime
from email.mime.text import MIMEText
from sickle import Sickle
import solr
import requests
import logbook
from logbook import FileHandler

URL_SOLR = os.environ.get('URL_SOLR', 'http://107.21.228.130:8080/solr/dc-collection/')
EMAIL_RETURN_ADDRESS = 'mark.redar@ucop.edu'

class Harvester(object):
    '''Base class for harvest objects.'''
    def __init__(self, url_harvest, extra_data):
        self.url = url_harvest
        self.extra_data = extra_data

    def __iter__(self):
        return self

    def next(self):
        raise NotImplementedError


class OAIHarvester(Harvester):
    '''Harvester for oai'''
    def __init__(self, url_harvest, extra_data):
        super(OAIHarvester, self).__init__(url_harvest, extra_data)
        #TODO: check extra_data?
        self.oai_client = Sickle(url_harvest)
        self.records = self.oai_client.ListRecords(set=extra_data, metadataPrefix='oai_dc')

    def next(self):
        '''return a record iterator? then outside layer is a controller, same for all. Records are dicts that include:
        any metadata
        campus list
        repo list
        collection name
        '''
        sickle_rec = self.records.next()
        rec = sickle_rec.metadata
        return rec

class OACHarvester(Harvester):
    '''Harvester for oac'''
    def __init__(self, url_harvest, extra_data):
        super(OACHarvester, self).__init__(url_harvest, extra_data)
        self.oac_findaid_ark = self._parse_oac_findaid_ark(url_harvest)
        self.objset_url_start = 'http://dsc.cdlib.org/search?rmode=json&facet=type-tab&style=cui&relation=' + self.oac_findaid_ark
        self.headers = {'content-type': 'application/json'}
        self.objset_index = 0
        self.resp = requests.get(self.objset_url_start, headers=self.headers)
        self.api_resp = self.resp.json()
        self.objset_total = self.api_resp['objset_total']
        self.objset_start = self.api_resp['objset_start']
        self.objset_end = self.api_resp['objset_end']
        self.objset = self.api_resp['objset']

    def _parse_oac_findaid_ark(self, url_findaid):
        return ''.join(('ark:', url_findaid.split('findaid/ark:')[1]))

    def next(self):
        '''Return the next record'''
        while self.resp:
            try:
                obj = self.objset.pop()
                return obj['qdc'] #self.objset.pop()
            except IndexError, e:
                if self.objset_end == self.objset_total:
                    self.resp = None
                    raise StopIteration
            url_next = ''.join((self.objset_url_start, '&startDoc=', unicode(self.objset_end+1)))
            self.resp = requests.get(url_next, headers=self.headers)
            self.api_resp = self.resp.json()
            #self.objset_total = api_resp['objset_total']
            self.objset_start = self.api_resp['objset_start']
            self.objset_end = self.api_resp['objset_end']
            self.objset = self.api_resp['objset']


class HarvestController(object):
    '''Controller for the harvesting. Selects correct harvester for the given 
    collection, then retrieves records for the given collection, massages them
    to match the solr schema and then sends to solr for updates.
    '''
    campus_valid = ['UCB', 'UCD', 'UCI', 'UCLA', 'UCM', 'UCR', 'UCSB', 'UCSC', 'UCSD', 'UCSF', 'UCDL']
    harvest_types = { 'OAI': OAIHarvester,
            'OAC': OACHarvester,
        }
    dc_elements = ['title', 'creator', 'subject', 'description', 'publisher', 'contributor', 'date', 'type', 'format', 'identifier', 'source', 'language', 'relation', 'coverage', 'rights']

    def __init__(self, user_email, collection_name, campuses, repositories, harvest_type, url_harvest, extra_data):
        self.user_email = user_email
        self.collection_name = collection_name
        self.campuses = []
        for campus in campuses:
            if campus not in self.campus_valid:
                raise ValueError('Campus value '+campus+' in not one of '+str(self.campus_valid))
            self.campuses.append(campus)
        self.repositories = repositories
        self.harvester = self.harvest_types.get(harvest_type, None)(url_harvest, extra_data)
        self.solr = solr.Solr(URL_SOLR)
        self.logger = logbook.Logger('HarvestController')

    def validate_input_dict(self, indata):
        '''Validate the data from the harvester. Currently only DC elements
        supported'''
        if not isinstance(indata, dict):
            raise TypeError("Input data must be a dictionary")
###        for key, value in indata.items():
###            if key not in self.dc_elements:
###                raise ValueError('Input data must be in DC elements. Problem key is:' + unicode(key))

    def create_solr_id(self, identifier):
        '''Create an id that is good for solr. Take campus, repo and collection
        name to form prefix to individual item id. Ensures unique ids in solr,
        in case any local ids are identical.
        May do something smarter when known GUIDs (arks, doi, etc) are in use.
        Takes a list of possible identifiers and creates a string id.
        '''
        if not isinstance(identifier, list):
            raise TypeError('Identifier field should be a list')
        campusStr = '-'.join(self.campuses)
        repoStr = '-'.join(self.repositories)
        sID = '-'.join((campusStr, repoStr, self.collection_name, identifier[0]))
        return sID

    def create_solr_doc(self, indata):
        '''Create a document that is compatible with our solr index.
        Currently it is not auto updated, this code will need to be touched
        when solr schema changes
        '''
        self.validate_input_dict(indata)
        #dc.title required
        if 'title' not in indata:
            raise ValueError('Item must have a title')
        sDoc = indata
        sDoc['id'] = self.create_solr_id(sDoc['identifier'])
        sDoc['collection_name'] = self.collection_name
        sDoc['campus'] = self.campuses
        sDoc['repository'] = self.repositories
        sDoc.pop('entity_count', None) #was added at one point
        return sDoc

    def harvest(self):
        '''Harvest the collection'''
        self.logger.info(' '.join(('Starting harvest for:', self.user_email, self.collection_name, str(self.campuses), str(self.repositories), str(self.solr) )))
        n = 0
        interval = 100
        for rec in self.harvester:
            #validate record
            try:
            	solrDoc = self.create_solr_doc(rec)
            except ValueError, e:
                self.logger.error(' '.join(('Error for record', str(rec), ' ERR:', str(e))))
                continue
            try:
                self.solr.add(solrDoc, commit=True)
                n += 1
            except solr.core.SolrException, e:
                if e.httpcode == 400:
                    self.logger.error(' '.join(('Error for record', str(rec), ' ERR:', str(e))))
                    continue
                raise e
            if n % interval == 0:
                self.logger.info(' '.join((str(n), 'records harvested')))
                if n < 10000 and n >= 10*interval:
                    interval = 10*interval
        return n

def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description='Harvest a collection')
    parser.add_argument('user_email', type=str, nargs='?', help='user email')
    parser.add_argument('collection_name', type=str, nargs='?',
            help='name of collection in registry')
    parser.add_argument('campuses', type=str, nargs='?',
            help='Comma delimited string of campuses')
    parser.add_argument('repositories', type=str, nargs='?',
            help='Comma delimited string of repositories')
    parser.add_argument('harvest_type', type=str, nargs='?', help='Type of harvest (Only OAI)')
    parser.add_argument('url_harvest', type=str, nargs='?', help='URL for harvest')
    parser.add_argument('extra_data', type=str, nargs='?', help='String of extra data required by type of harvest')
    return parser.parse_args()

def get_log_file_path(collection_name):
    '''Get the log file name for the given collection, start time and environment
    '''
    log_file_dir = os.environ.get('DIR_HARVESTER_LOG', os.path.join(os.environ.get('HOME', '.'), 'log'))
    log_file_name = 'harvester-' + collection_name + '-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.log'
    return os.path.join(log_file_dir, log_file_name)

def create_mimetext_msg(mail_from, mail_to, subject, message):
    msg = MIMEText(message)
    msg['Subject'] = str(subject)
    msg['From'] = mail_from
    msg['To'] = mail_to
    return msg

def main(log_handler=None, mail_handler=None):
    args = parse_args()
    campus_list = args.campuses.split(',')
    repository_list = args.repositories.split(':-:')
    if not log_handler:
        log_handler = FileHandler(get_log_file_path(args.collection_name))
    if not mail_handler:
        mail_handler = logbook.MailHandler(EMAIL_RETURN_ADDRESS, args.user_email, level=logbook.ERROR, subject="Error during harvest of "+args.collection_name)
    with log_handler.applicationbound():
        with mail_handler.applicationbound():
            logger = logbook.Logger('HarvestMain')
            logger.info('Init harvester next')
            msg = ' '.join(('ARGS:', args.user_email, args.collection_name, str(campus_list), str(repository_list), args.harvest_type, args.url_harvest, args.extra_data))
            logger.info(msg)
            #email directly
            mimetext = create_mimetext_msg(EMAIL_RETURN_ADDRESS, args.user_email, ' '.join(('Starting harvest for ', args.collection_name)), msg)
            mail_handler.deliver(mimetext, args.user_email)
            harvester = None
            try:
                harvester = HarvestController(args.user_email, args.collection_name, campus_list, repository_list, args.harvest_type, args.url_harvest, args.extra_data)
            except Exception, e:
                logger.error(' '.join(("Exception in harvester init", str(e))))
                raise e
            logger.info('Start harvesting next')
            try:
                num_recs = harvester.harvest()
                msg = ''.join(('Finished harvest of ', args.collection_name, '. ', str(num_recs), ' records harvested.'))
                logger.info(msg)
                #email directly
                mimetext = create_mimetext_msg(EMAIL_RETURN_ADDRESS, args.user_email, ' '.join(('Finished harvest for ', args.collection_name)), msg)
                mail_handler.deliver(mimetext, args.user_email)
            except Exception, e:
                import traceback
                logger.error("Error while harvesting: type-> "+str(type(e))+ " TRACE:\n"+str(traceback.format_exc()))

if __name__=='__main__':
    main()
