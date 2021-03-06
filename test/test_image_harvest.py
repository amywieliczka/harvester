import os
from unittest import TestCase
from collections import namedtuple
from mock import patch
from mock import MagicMock
from mypretty import httpretty
# import httpretty
from harvester import image_harvest
from harvester.image_harvest import FailsImageTest
from harvester.image_harvest import ImageHTTPError
from harvester.image_harvest import IsShownByError
from harvester.image_harvest import HasObject
from harvester.image_harvest import RestoreFromObjectCache

#TODO: make this importable from md5s3stash
StashReport = namedtuple('StashReport',
                         'url, md5, s3_url, mime_type, dimensions')


class ImageHarvestTestCase(TestCase):
    '''Test the md5 s3 image harvesting calls.....
    TODO: Increase test coverage
    '''

    def setUp(self):
        self.old_url_couchdb = os.environ.get('COUCHDB_URL', None)
        os.environ['COUCHDB_URL'] = 'http://example.edu/test'

    def tearDown(self):
        if self.old_url_couchdb:
            os.environ['COUCHDB_URL'] = self.old_url_couchdb

    @patch('boto.s3.connect_to_region', return_value='S3Conn to a region')
    @patch('harvester.image_harvest.Redis', autospec=True)
    @patch('couchdb.Server')
    @patch(
        'md5s3stash.md5s3stash',
        autospec=True,
        return_value=StashReport('test url', 'md5 test value', 's3 url object',
                                 'mime_type', 'dimensions'))
    @httpretty.activate
    def test_stash_image(self, mock_stash, mock_couch, mock_redis,
                         mock_s3_connect):
        '''Test the stash image calls are correct'''
        doc = {'_id': 'TESTID'}
        image_harvester = image_harvest.ImageHarvester(
            url_cache={}, hash_cache={}, bucket_bases=['region:x'])
        self.assertRaises(IsShownByError, image_harvester.stash_image, doc)
        doc['isShownBy'] = None
        self.assertRaises(IsShownByError, image_harvester.stash_image, doc)
        doc['isShownBy'] = ['ark:/test_local_url_ark:']
        url_test = 'http://content.cdlib.org/ark:/test_local_url_ark:'
        httpretty.register_uri(
            httpretty.HEAD,
            url_test,
            body='',
            content_length='0',
            content_type='image/jpeg;',
            connection='close', )
        ret = image_harvester.stash_image(doc)
        mock_stash.assert_called_with(
            url_test,
            url_auth=None,
            bucket_base='x',
            conn='S3Conn to a region',
            hash_cache={},
            url_cache={})
        self.assertEqual('s3 url object', ret[0].s3_url)
        ret = image_harvester.stash_image(doc)
        mock_stash.assert_called_with(
            url_test,
            url_auth=None,
            bucket_base='x',
            conn='S3Conn to a region',
            hash_cache={},
            url_cache={})
        ret = image_harvest.ImageHarvester(
            bucket_bases=['region:x'],
            object_auth=('tstuser', 'tstpswd'),
            url_cache={},
            hash_cache={}).stash_image(doc)
        mock_stash.assert_called_with(
            url_test,
            url_auth=('tstuser', 'tstpswd'),
            bucket_base='x',
            conn='S3Conn to a region',
            hash_cache={},
            url_cache={})
        doc['isShownBy'] = ['not a url']
        self.assertRaises(FailsImageTest, image_harvester.stash_image, doc)

    def test_update_doc_object(self):
        '''Test call to couchdb, right data'''
        doc = {'_id': 'TESTID'}
        r = StashReport('s3 test2 url', 'md5 test value', 's3 url',
                        'mime_type', 'dimensions-x:y')
        db = MagicMock()
        image_harvester = image_harvest.ImageHarvester(
            cdb=db, url_cache={}, hash_cache={}, bucket_bases=['region:x'])
        ret = image_harvester.update_doc_object(doc, r)
        self.assertEqual('md5 test value', ret)
        self.assertEqual('md5 test value', doc['object'])
        self.assertEqual(doc['object_dimensions'], 'dimensions-x:y')
        db.save.assert_called_with({
            '_id': 'TESTID',
            'object': 'md5 test value',
            'object_dimensions': 'dimensions-x:y'
        })

    @httpretty.activate
    def test_link_is_to_image(self):
        '''Test the link_is_to_image function'''
        url = 'http://getthisimage/notauthorized'
        httpretty.register_uri(
            httpretty.HEAD,
            url,
            body='',
            content_length='0',
            content_type='text/plain; charset=utf-8',
            connection='close',
            status=401)
        httpretty.register_uri(
            httpretty.GET,
            url,
            body='',
            content_length='0',
            content_type='text/html; charset=utf-8',
            connection='close',
            status=401)
        self.assertRaises(ImageHTTPError, image_harvest.link_is_to_image,
                          'TESTID', url)
        url = 'http://getthisimage/notanimage'
        httpretty.register_uri(
            httpretty.HEAD,
            url,
            body='',
            content_length='0',
            content_type='text/plain; charset=utf-8',
            connection='close', )
        httpretty.register_uri(
            httpretty.GET,
            url,
            body='',
            content_length='0',
            content_type='text/html; charset=utf-8',
            connection='close', )
        self.assertFalse(image_harvest.link_is_to_image('TESTID', url))
        url = 'http://getthisimage/isanimage'
        httpretty.register_uri(
            httpretty.HEAD,
            url,
            body='',
            content_length='0',
            content_type='image/jpeg; charset=utf-8',
            connection='close', )
        self.assertTrue(image_harvest.link_is_to_image('TESTID', url))
        url_redirect = 'http://gethisimage/redirect'
        httpretty.register_uri(
            httpretty.HEAD, url, body='', status=301, location=url_redirect)
        httpretty.register_uri(
            httpretty.HEAD,
            url_redirect,
            body='',
            content_length='0',
            content_type='image/jpeg; charset=utf-8',
            connection='close', )
        self.assertTrue(image_harvest.link_is_to_image('TESTID', url))
        httpretty.register_uri(
            httpretty.HEAD,
            url,
            body='',
            content_length='0',
            content_type='text/html; charset=utf-8',
            connection='close', )
        httpretty.register_uri(
            httpretty.GET,
            url,
            body='',
            content_length='0',
            content_type='image/jpeg; charset=utf-8',
            connection='close', )
        self.assertTrue(image_harvest.link_is_to_image('TESTID', url))

    @patch('couchdb.Server')
    @patch(
        'md5s3stash.md5s3stash',
        autospec=True,
        return_value=StashReport('test url', 'md5 test value', 's3 url object',
                                 'mime_type', 'dimensions'))
    @httpretty.activate
    def test_ignore_content_type(self, mock_stash, mock_couch):
        '''Test that content type check is not called if  --ignore_content_type parameter given'''
        url = 'http://getthisimage/image'
        doc = {'_id': 'IGNORE_CONTENT', 'isShownBy': url}
        httpretty.register_uri(
            httpretty.HEAD,
            url,
            body='',
            content_length='0',
            content_type='text/plain; charset=utf-8',
            connection='close', )
        httpretty.register_uri(
            httpretty.GET,
            url,
            body='',
            content_length='0',
            content_type='text/html; charset=utf-8',
            connection='close', )
        image_harvester = image_harvest.ImageHarvester(
            url_cache={}, hash_cache={}, bucket_bases=['region:x'], ignore_content_type=True)
        r = StashReport('test url', 'md5 test value', 's3 url object',
                        'mime_type', 'dimensions')
        ret = image_harvester.stash_image(doc)
        self.assertEqual(ret, [r])

    @patch('couchdb.Server')
    @patch(
        'md5s3stash.md5s3stash',
        autospec=True,
        return_value=StashReport('test url', 'md5 test value', 's3 url object',
                                 'mime_type', 'dimensions'))
    @httpretty.activate
    def test_check_content_type(self, mock_stash, mock_couch):
        '''Test that the check for content type correctly aborts if the
        type is not a image
        '''
        url = 'http://getthisimage/notanimage'
        doc = {'_id': 'TESTID', 'isShownBy': url}
        httpretty.register_uri(
            httpretty.HEAD,
            url,
            body='',
            content_length='0',
            content_type='text/plain; charset=utf-8',
            connection='close', )
        httpretty.register_uri(
            httpretty.GET,
            url,
            body='',
            content_length='0',
            content_type='text/html; charset=utf-8',
            connection='close', )
        image_harvester = image_harvest.ImageHarvester(
            url_cache={}, hash_cache={}, bucket_bases=['region:x'])
        self.assertRaises(FailsImageTest, image_harvester.stash_image, doc)
        httpretty.register_uri(
            httpretty.HEAD,
            url,
            body='',
            content_length='0',
            content_type='image/plain; charset=utf-8',
            connection='close', )
        r = StashReport('test url', 'md5 test value', 's3 url object',
                        'mime_type', 'dimensions')
        ret = image_harvester.stash_image(doc)
        self.assertEqual(ret, [r])

    @patch('boto.s3.connect_to_region', return_value='S3Conn to a region')
    @patch('harvester.image_harvest.Redis', autospec=True)
    @patch('couchdb.Server')
    @patch(
        'md5s3stash.md5s3stash',
        autospec=True,
        return_value=StashReport('test url', 'md5 test value', 's3 url object',
                                 'mime_type', 'dimensions'))
    @httpretty.activate
    def test_harvest_image_for_doc(self, mock_stash, mock_couch, mock_redis,
                                   mock_s3_connect):
        image_harvester = image_harvest.ImageHarvester(
            url_cache={},
            hash_cache={},
            bucket_bases=['region:x'],
            harvested_object_cache={'xxx': 'yyy'})
        doc = {
            '_id': 'TESTID',
            'object': 'hasobject',
            'object_dimensions': 'x:y'
        }
        self.assertRaises(HasObject, image_harvester.harvest_image_for_doc,
                          doc)
        doc = {'_id': 'xxx', }
        self.assertRaises(RestoreFromObjectCache,
                          image_harvester.harvest_image_for_doc, doc)
        doc = {'_id': 'TESTID', }
        self.assertRaises(RestoreFromObjectCache,
                          image_harvester.harvest_image_for_doc, doc)
        doc = {'_id': 'XXX-TESTID', }
        self.assertRaises(IsShownByError,
                          image_harvester.harvest_image_for_doc, doc)
        doc = {'_id': 'XXX-TESTID', 'isShownBy': 'bogus'}
        self.assertRaises(FailsImageTest,
                          image_harvester.harvest_image_for_doc, doc)
        url = 'http://example.edu/test.jpg'
        doc = {'_id': 'XXX-TESTID', 'isShownBy': url}
        httpretty.register_uri(
            httpretty.HEAD,
            url,
            body='',
            content_length='0',
            content_type='image/plain; charset=utf-8',
            connection='close', )
        report = image_harvester.harvest_image_for_doc(doc)
        print '++++++++ REPORT:{}'.format(report)

    def test_url_missing_schema(self):
        '''Test when the url is malformed and doesn't have a proper http
        schema. The LAPL photo feed has URLs like this:

        http:/jpg1.lapl.org/pics47/00043006.jpg

        The code was choking complaining about a "MissingSchema"
        exception.
        '''
        pass
