#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import datetime
from esi_leap.common import statuses
from esi_leap.db import api as dbapi
from esi_leap.objects import base
import esi_leap.objects.contract
from esi_leap.objects import fields
from esi_leap.objects import flocx_market_client
from esi_leap.resource_objects import resource_object_factory as ro_factory
from keystoneauth1 import adapter
from keystoneauth1 import loading as ks_loading
from oslo_config import cfg
from oslo_versionedobjects import base as versioned_objects_base

CONF = cfg.CONF


@versioned_objects_base.VersionedObjectRegistry.register
class Offer(base.ESILEAPObject):
    dbapi = dbapi.get_instance()

    fields = {
        'id': fields.IntegerField(),
        'uuid': fields.UUIDField(),
        'project_id': fields.StringField(),
        'resource_type': fields.StringField(),
        'resource_uuid': fields.StringField(),
        'start_date': fields.DateTimeField(nullable=True),
        'end_date': fields.DateTimeField(nullable=True),
        'status': fields.StringField(),
        'properties': fields.FlexibleDictField(nullable=True),
    }

    @classmethod
    def get(cls, context, offer_uuid):
        db_offer = cls.dbapi.offer_get(context, offer_uuid)
        return cls._from_db_object(context, cls(), db_offer)

    @classmethod
    def get_all(cls, context):
        db_offers = cls.dbapi.offer_get_all(context)
        return cls._from_db_object_list(context, db_offers)

    @classmethod
    def get_all_by_project_id(cls, context, project_id):
        db_offers = cls.dbapi.offer_get_all_by_project_id(
            context, project_id)
        return cls._from_db_object_list(context, db_offers)

    @classmethod
    def get_all_by_status(cls, context, status):
        db_offers = cls.dbapi.offer_get_all_by_status(
            context, status)
        return cls._from_db_object_list(context, db_offers)

    def send_to_flocx_market(self):
        auth_plugin = ks_loading.load_auth_from_conf_options(
            CONF, 'flocx_market')
        sess = ks_loading.load_session_from_conf_options(CONF, 'flocx_market',
                                                         auth=auth_plugin)
        marketplace_offer_dict = self.to_marketplace_dict()

        adpt = adapter.Adapter(
            session=sess,
            service_type='marketplace',
            interface='public')
        marketplace_client = flocx_market_client.FlocxMarketClient(adpt)
        res_status_code = marketplace_client.send_offer(marketplace_offer_dict)

        return res_status_code

    def create(self, context=None):
        updates = self.obj_get_changes()
        db_offer = self.dbapi.offer_create(context, updates)
        o = self._from_db_object(context, self, db_offer)
        return o.send_to_flocx_market()

    def destroy(self, context=None):
        self.dbapi.offer_destroy(context, self.uuid)
        self.obj_reset_changes()

    def save(self, context=None):
        updates = self.obj_get_changes()
        db_offer = self.dbapi.offer_update(
            context, self.uuid, updates)
        self._from_db_object(context, self, db_offer)

    def resource_object(self):
        return ro_factory.ResourceObjectFactory.get_resource_object(
            self.resource_type, self.resource_uuid)

    def expire(self, context=None):
        # make sure all related contracts are expired
        contracts = esi_leap.objects.contract.Contract.get_all_by_offer_uuid(
            context, self.uuid)
        for c in contracts:
            if c.status != statuses.EXPIRED:
                c.expire(context)

        # expire offer
        self.status = statuses.EXPIRED
        self.save(context)

    def to_marketplace_dict(self):
        # change fields name
        offer_dict = self.to_dict()
        resource = self.resource_object()
        offer_dict['server_config'] = resource.get_node_config()
        offer_dict['start_time'] = offer_dict.pop('start_date').isoformat()
        offer_dict['end_time'] = offer_dict.pop('end_date').isoformat()
        offer_dict['cost'] = offer_dict['properties'].get('floor_price', 0)
        offer_dict['server_id'] = offer_dict.pop('resource_uuid')
        offer_dict['provider_offer_id'] = offer_dict.pop('uuid')
        offer_dict['project_id'] = offer_dict.pop('project_id')
        # remove unnecessary feilds
        offer_dict.pop('created_at')
        offer_dict.pop('updated_at')
        offer_dict.pop('id')
        offer_dict.pop('resource_type')
        # fake fields
        offer_dict['marketplace_date_created'] = datetime.datetime.utcnow()

        return offer_dict
