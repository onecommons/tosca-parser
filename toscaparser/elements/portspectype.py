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

    @staticmethod
    def make(*args, **kw):
        """
        Parse "source['-'range][':'target['-'range]]['/'protocol]"
        """
        # XXX should be __new__ or __init__
        if len(args) != 1:
            p = PortSpec(*args, **kw)
        else:
            spec = args[0]
            if not spec:
                p = PortSpec()
            elif isinstance(spec, int):
                p = PortSpec(source=spec, target=spec)
            elif isinstance(spec, str):
                ports, sep, protocol = spec.partition('/')
                d = dict(protocol=protocol or 'tcp')
                source, sep, target = ports.partition(':')
                if not target:
                    target = source
                if '-' in source:
                    d["source_range"] = source.split('-')
                else:
                    d["source"] = source
                if '-' in target:
                    d["target_range"] = target.split('-')
                else:
                    d["target"] = target
                p = PortSpec(**d)
            else:
                p = PortSpec(spec, **kw)
        p.validate()
        return p

    @property
    def spec(self):
        """
        Translate a `tosca:PortSpec` into a string like "source-range:target-range/udp"
        or "source:target" or just "source" if target is missing or the same.
        """
        if self.get("source_range") is not None:
            source = "{:d}-{:d}".format(*self["source_range"])
        else:
            source = "{}".format(self.get("source", ""))
        if self.get("target_range") is not None:
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
        # use setdefault() to make sure attributes exist
        source = self.setdefault(PortSpec.SOURCE, None)
        source_range = self.setdefault(PortSpec.SOURCE_RANGE, None)
        target = self.setdefault(PortSpec.TARGET, None)
        target_range = self.setdefault(PortSpec.TARGET_RANGE, None)
        self.setdefault(PortSpec.PROTOCOL, None)

        # verify one of the specified values is set
        if source is None and source_range is None and \
                target is None and target_range is None:
            ExceptionCollector.appendException(
                InvalidTypeAdditionalRequirementsError(
                    type=PortSpec.TYPE_URI))

        # Validate source value is in specified range
        if source_range:
            source_range = validateutils.validate_range(source_range)
        if source is not None:
            self[PortSpec.SOURCE] = source = validateutils.validate_portdef(source, PortSpec.SOURCE)
            if source_range:
                validateutils.validate_value_in_range(source, source_range,
                                                  PortSpec.SOURCE)

        # Validate target value is in specified range
        if target_range:
            target_range = validateutils.validate_range(target_range)
        if target is not None:
            self[PortSpec.TARGET] = target = validateutils.validate_portdef(source, PortSpec.TARGET)
            if target_range:
                validateutils.validate_value_in_range(target, target_range,
                                                  PortSpec.TARGET)
