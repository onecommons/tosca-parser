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

from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import MissingRequiredFieldError
from toscaparser.common.exception import UnknownFieldError
from toscaparser.common.exception import TypeMismatchError
from toscaparser.common.exception import URLException
from toscaparser.utils.gettextutils import _
import toscaparser.utils.urlutils
from six.moves.urllib.parse import urlparse
from toscaparser.dataentity import DataEntity

SECTIONS = (DESCRIPTION, URL, CREDENTIAL, METADATA) = \
           ('description', 'url', 'credential', 'metadata')


class Repository(object):
    def __init__(self, name, values):
        self.name = name
        self.tpl = values
        if isinstance(self.tpl, dict):
            if URL not in self.tpl.keys():
                ExceptionCollector.appendException(
                    MissingRequiredFieldError(what=_('repository "%s"')
                                              % self.name, required='url'))
            for key, value in self.tpl.items():
                if key not in SECTIONS:
                    ExceptionCollector.appendException(
                        UnknownFieldError(what=_('repository "%s"')
                                          % name, field=key))
                setattr(self, key, value)

            self.validate()
            self.hostname = urlparse(self.url).hostname
        else:
            ExceptionCollector.appendException(
                TypeMismatchError(what=_('repository "%s"') % self.name, type="dict"))

    def validate(self):
        url_val = toscaparser.utils.urlutils.UrlUtils.validate_url(self.url)
        if url_val is not True:
            ExceptionCollector.appendException(
                URLException(what=_('repository "%s": Invalid Url "%s"')
                             % (self.name, self.url)))
        if self.credential:
            self.credential = DataEntity("tosca.datatypes.Credential",
                                  self.credential, prop_name=CREDENTIAL).validate()

for key in SECTIONS:
  setattr(Repository, key, None)
