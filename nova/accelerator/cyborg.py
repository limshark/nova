# Copyright 2019 Intel
#
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

from oslo_log import log as logging

from nova import service_auth
from nova import utils


LOG = logging.getLogger(__name__)


def get_client(context):
    return _CyborgClient(context)


class _CyborgClient(object):

    def __init__(self, context):
        auth = service_auth.get_auth_plugin(context)
        self._client = utils.get_ksa_adapter('accelerator', ksa_auth=auth)
