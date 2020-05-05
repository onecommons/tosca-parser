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

import logging

from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import InvalidTypeAdditionalRequirementsError
from toscaparser.utils.gettextutils import _
import toscaparser.utils.validateutils as validateutils


log = logging.getLogger('tosca')


class PortSpec(dict):
    '''Parent class for tosca.datatypes.network.PortSpec type.'''

    SHORTNAME = 'PortSpec'
    TYPE_URI = 'tosca.datatypes.network.' + SHORTNAME

    PROPERTY_NAMES = (
        PROTOCOL, SOURCE, SOURCE_RANGE,
        TARGET, TARGET_RANGE
    ) = (
        'protocol', 'source', 'source_range',
        'target', 'target_range'
    )

    def __str__(self):
        """
        Translate a `tosca:PortSpec` into a string like "source-range:target-range/udp"
        or "source:target" or just "source" if target is missing or the same.
        """
        if "source_range" in self:
            source = "{:d}-{:d}".format(*self["source_range"])
        else:
            source = "{}".format(self.get("source", ""))
        if "target_range" in self:
            target = "{:d}-{:d}".format(*self["target_range"])
        else:
            target = "{}".format(self.get("target", ""))
        if source == target or not target:
            portSpec = str(source)
        else:
            portSpec = "{}:{}".format(target, source)
        protocol = self.get("protocol", "tcp")
        if protocol != "tcp":
            portSpec += "/" + protocol
        return portSpec

    # The following additional requirements MUST be tested:
    # 1) A valid PortSpec MUST have at least one of the following properties:
    #   target, target_range, source or source_range.
    # 2) A valid PortSpec MUST have a value for the source property that
    #    is within the numeric range specified by the property source_range
    #    when source_range is specified.
    # 3) A valid PortSpec MUST have a value for the target property that is
    #    within the numeric range specified by the property target_range
    #    when target_range is specified.
    def validate(self):
        from toscaparser.dataentity import DataEntity
        # TODO(TBD) bug 1567063, validate source & target as PortDef type
        # not just as integers
        try:
            source = self.get(PortSpec.SOURCE)
            source_range = self.get(PortSpec.SOURCE_RANGE)
            target = self.get(PortSpec.TARGET)
            target_range = self.get(PortSpec.TARGET_RANGE)

            # verify one of the specified values is set
            if source is None and source_range is None and \
                    target is None and target_range is None:
                ExceptionCollector.appendException(
                    InvalidTypeAdditionalRequirementsError(
                        type=PortSpec.TYPE_URI))
            # Validate source value is in specified range
            if source:
                if source_range:
                    validateutils.validate_value_in_range(source, source_range,
                                                      PortSpec.SOURCE)
                else:
                    portdef = DataEntity('PortDef', source, None, PortSpec.SOURCE)
                    portdef.validate()
            # Validate target value is in specified range
            if target:
                if target_range:
                    validateutils.validate_value_in_range(target, target_range,
                                                      PortSpec.TARGET)
                else:
                    portdef = DataEntity('PortDef', target, None, PortSpec.TARGET)
                    portdef.validate()
        except Exception:
            msg = _('"%(value)s" do not meet requirements '
                    'for type "%(type)s".') \
                % {'value': self, 'type': PortSpec.SHORTNAME}
            ExceptionCollector.appendException(
                ValueError(msg))
