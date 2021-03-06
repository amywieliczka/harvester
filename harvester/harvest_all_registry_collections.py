from harvester.collection_registry_client import ResourceIterator
from harvester.collection_registry_client import url_base, api_path
from harvester.config import config
from harvester.scripts.queue_harvest import main as queue_harvest

for c in ResourceIterator(url_base, api_path+'collection', 'collection'):
    if c.harvest_type != 'X':
        print c.name, c.slug, c.harvest_type, c.url_harvest
        env = config()
        queue_harvest('mark.redar@ucop.edu', url_base+c.resource_uri,
                      redis_host=env['redis_host'],
                      redis_port=env['redis_port'],
                      redis_pswd=env['redis_password'],
                      id_ec2_ingest=env['id_ec2_ingest'],
                      id_ec2_solr=env['id_ec2_solr_build'],
                      job_timeout=6000
                      )
