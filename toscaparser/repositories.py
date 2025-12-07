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
from urllib.parse import urlparse
from toscaparser.dataentity import DataEntity

SECTIONS = (DESCRIPTION, URL, CREDENTIAL, REVISION, METADATA, FILE) = \
           ('description', 'url', 'credential', 'revision', 'metadata', 'file')


class Repository(object):
    url = ""
    description = None
    credential = None
    revision = None
    metadata = None
    file = None
    hostname = None

    def __init__(self, name, tpl):
        self.name = name
        # TOSCA 1.0 backwards compatibility:
        if isinstance(tpl, str):
            self.tpl = dict(url=tpl)
        elif isinstance(tpl, dict):
            self.tpl = tpl
            if URL not in tpl.keys():
                ExceptionCollector.appendException(
                    MissingRequiredFieldError(what=_('repository "%s"')
                                              % self.name, required='url'))
            self.url = tpl.get("url")
            for key, value in tpl.items():
                if key not in SECTIONS:
                    ExceptionCollector.appendException(
                        UnknownFieldError(what=_('repository "%s"')
                                          % name, field=key))
                elif key != "url":
                    setattr(self, key, value)
            self.validate()
            self.hostname = urlparse(self.url).hostname
        else:
            self.tpl = tpl
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
