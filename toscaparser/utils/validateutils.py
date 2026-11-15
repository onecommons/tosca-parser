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

import collections.abc
import dateutil.parser
import logging
import numbers
import re

# from toscaparser.elements import constraints
from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import InvalidTOSCAVersionPropertyException
from toscaparser.common.exception import RangeValueError
from toscaparser.utils.gettextutils import _

log = logging.getLogger('tosca')

RANGE_UNBOUNDED = 'UNBOUNDED'


def str_to_num(value):
    '''Convert a string representation of a number into a numeric type.'''
    # TODO(TBD) we should not allow numeric values in, input should be str
    if isinstance(value, numbers.Number):
        return value
    try:
        return int(value)
    except ValueError:
        return float(value)


def validate_numeric(value):
    if not isinstance(value, numbers.Number):
        try:
            value = float(value)
        except Exception:
            ExceptionCollector.appendException(
                ValueError(_('"%s" is not a numeric.') % value))
    return value


def validate_integer(value):
    if not isinstance(value, int):
        try:
            value = int(value)
        except Exception:
            ExceptionCollector.appendException(
                ValueError(_('"%s" is not an integer.') % value))
    return value


def validate_portdef(value, prop_name="PortDef"):
    if not isinstance(value, int):
        try:
            value = int(value)
        except Exception:
            ExceptionCollector.appendException(
                ValueError(_('"%s" is not an integer.') % value))
    validate_value_in_range(value, [1, 65535], prop_name)
    return value


def validate_float(value):
    if not isinstance(value, float):
        try:
            value = float(value)
        except Exception:
            ExceptionCollector.appendException(
                ValueError(_('"%s" is not a float.') % value))
    return value


def validate_string(value):
    if not isinstance(value, str):
        ExceptionCollector.appendException(
            ValueError(_('"%s" is not a string.') % value))
    return value


def validate_list(value):
    if not isinstance(value, collections.abc.MutableSequence):
        ExceptionCollector.appendException(
            ValueError(f'"{value}" is not a list.'))
    return value


def validate_range(range):
    # list class check
    validate_list(range)
    # validate range list has a min and max
    if len(range) != 2:
        ExceptionCollector.appendException(
            ValueError(_('"%s" is not a valid range.') % range))
    # validate min and max are numerics or the keyword UNBOUNDED
    min_test = max_test = False
    if range[0] != RANGE_UNBOUNDED:
        min = validate_numeric(range[0])
    else:
        min_test = True
    if range[1] != RANGE_UNBOUNDED:
        max = validate_numeric(range[1])
    else:
        max_test = True
    # validate the max > min (account for UNBOUNDED)
    if not min_test and not max_test:
        # Note: min == max is allowed
        if min > max:
            ExceptionCollector.appendException(
                ValueError(_('"%s" is not a valid range.') % range))
        return [min, max]

    return range


def validate_value_in_range(value, range, prop_name):
    validate_numeric(value)
    validate_range(range)

    # Note: value is valid if equal to min
    if range[0] != RANGE_UNBOUNDED:
        if value < range[0]:
            ExceptionCollector.appendException(
                RangeValueError(pname=prop_name,
                                pvalue=value,
                                vmin=range[0],
                                vmax=range[1]))
    # Note: value is valid if equal to max
    if range[1] != RANGE_UNBOUNDED:
        if value > range[1]:
            ExceptionCollector.appendException(
                RangeValueError(pname=prop_name,
                                pvalue=value,
                                vmin=range[0],
                                vmax=range[1]))
    return value


def validate_map(value):
    if not isinstance(value, collections.abc.Mapping):
        ExceptionCollector.appendException(
            ValueError(_('"%s" is not a map.') % value))
    return value


def validate_boolean(value):
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalised = value.lower()
        if normalised in ['true', 'false']:
            return normalised == 'true'

    ExceptionCollector.appendException(
        ValueError(_('"%s" is not a boolean.') % value))


def validate_timestamp(value):
    try:
        # Note: we must return our own exception message
        # as dateutil's parser returns different types / values on
        # different systems. OSX, for example, returns a tuple
        # containing a different error message than Linux
        dateutil.parser.parse(value)
    except Exception as e:
        original_err_msg = str(e)
        log.error(original_err_msg)
        ExceptionCollector.appendException(
            ValueError(_('"%(val)s" is not a valid timestamp. "%(msg)s"') %
                       {'val': value, 'msg': original_err_msg}))
    return


class TOSCAVersionProperty(object):
    VERSION_RE = re.compile(
        r"^[\^~]?v?(?P<major_version>([0-9]+))"
        r"(\.(?P<minor_version>([0-9]+)))?"
        r"(\.(?P<fix_version>([0-9]+)))?"
        # without a qualifier, "-N" is a semver pre-release, not a build version
        r"(\.(?P<qualifier>([0-9A-Za-z]+))(\-(?P<build_version>([0-9]+)))?)?"
        r"(\-(?P<pre_release>([0-9A-Za-z.\-]+)))?"
        r"(\+(?P<build_metadata>([0-9A-Za-z.\-]+)))?$"
    )

    def __init__(self, version):
        self.version = str(version)
        match = self.VERSION_RE.match(self.version)
        if not match:
            ExceptionCollector.appendException(
                InvalidTOSCAVersionPropertyException(what=(self.version)))
            return
        ver = match.groupdict()
        self.minor_version = ver['minor_version']
        self.major_version = str(int(ver['major_version']))
        self.fix_version = ver['fix_version']
        self.qualifier = ver['qualifier']
        self.pre_release = ver['pre_release']
        self.build_version = ver['build_version']
        # build_metadata comes after fix (aka patch) or pre_release
        self.build_metadata = ver['build_metadata']
        for valid in self._checks(ver):
            if not valid:
                ExceptionCollector.appendException(
                    InvalidTOSCAVersionPropertyException(what=(self.version)))

    @classmethod
    def is_valid(cls, test):
        return cls.VERSION_RE.match(test) is not None

    @classmethod
    def is_well_formed(cls, version):
        """Whether constructing a TOSCAVersionProperty from ``version`` would
        succeed, without reporting to the ExceptionCollector."""
        match = cls.VERSION_RE.match(str(version))
        return match is not None and all(cls._checks(match.groupdict()))

    @staticmethod
    def _checks(ver):
        """The validity of each part of a parsed version.

           A qualifier, pre-release or build metadata needs the fix version
           and isn't allowed when major, minor and fix version are all 0
           (18.0.abc and 0.0.0.abc are invalid). A qualifier (TOSCA/maven
           style) and a pre-release (semver style) are mutually exclusive.
        """
        all_zero = (ver['minor_version'] == str(int(ver['major_version'])) ==
                    ver['fix_version'] == '0')

        def suffix_ok(value):
            return not value or (ver['fix_version'] is not None and not all_zero)

        return [
            suffix_ok(ver['qualifier']),
            suffix_ok(ver['pre_release']),
            not (ver['pre_release'] and ver['qualifier']),
            suffix_ok(ver['build_metadata']),
        ]

    def get_version(self):
        return self.version

    def is_semver_compatible_with(self, version):
        """Return true if major version is equal and minor version is less than or equal to the given version."""
        return int(self.major_version) == int(version.major_version) and int(self.minor_version or 0) <= int(version.minor_version or 0)

    def has_minimum_version(self, version):
        """Return true if version satisfies tilde requirement semantics.

        Tilde requirements specify patch-level compatibility:
        - ~1.2.3 allows >=1.2.3, <1.3.0 (patch-level changes only)
        - ~1.2 allows >=1.2.0, <1.3.0 (patch-level changes only)
        - ~1 allows >=1.0.0, <2.0.0 (minor- and patch-level changes)
        """
        req_major = int(self.major_version)
        req_minor = int(self.minor_version or 0)

        ver_major = int(version.major_version)
        ver_minor = int(version.minor_version or 0)

        # Major version must match
        if req_major != ver_major:
            return False

        # Minor version must match for patch-level compatibility,
        # unless only the major version was specified (~1)
        if self.minor_version is not None and req_minor != ver_minor:
            return False

        # Version must be >= requirement
        return version.precedence() >= self.precedence()

    def version_tuple(self):
        return (
            int(self.major_version),
            int(self.minor_version or 0),
            int(self.fix_version or 0),
        )

    def precedence(self):
        """``version_tuple()``, extended to order pre-releases as semver does:
        below their release, identifier by identifier, numeric ones
        numerically and before alphanumeric ones. Build metadata and a
        TOSCA qualifier are ignored."""
        if not self.pre_release:
            return self.version_tuple() + ((1,),)
        identifiers = tuple(
            (0, int(part), "") if part.isdigit() else (1, 0, part)
            for part in self.pre_release.split(".")
        )
        return self.version_tuple() + ((0,) + identifiers,)

    def caret_limit(self):
        """The ``version_tuple()`` a caret requirement for this version stays
        below: the next increment of its leftmost non-zero part, or of its
        last given part if they're all 0 (^1.2.3 and ^1 are below 2.0.0,
        ^0.2.3 below 0.3.0, ^0.0.3 below 0.0.4, ^0.0 below 0.1.0)."""
        major = int(self.major_version)
        if self.minor_version is None or major:
            return (major + 1, 0, 0)
        minor = int(self.minor_version)
        if self.fix_version is None or minor:
            return (0, minor + 1, 0)
        return (0, 0, int(self.fix_version) + 1)

    def partial_limit(self):
        """The ``version_tuple()`` above every version this one matches when it
        leaves out the fix version (1.2 matches 1.2.x, so below 1.3.0) or
        minor version (1 matches 1.x.x, so below 2.0.0); None if it doesn't."""
        if self.fix_version is not None:
            return None
        major = int(self.major_version)
        if self.minor_version is None:
            return (major + 1, 0, 0)
        return (major, int(self.minor_version) + 1, 0)

    def compare_version(self, test_version, operator):
        """Compare two TOSCAVersionProperty objects using the given operator.

        As in npm and Cargo, a requirement that leaves out a part means every
        version it matches: =1.2 is >=1.2.0, <1.3.0; <=1.2 is <1.3.0; and
        >1.2 is >=1.3.0.
        """
        test_tuple = test_version.precedence()
        req_tuple = self.precedence()
        # a 3-tuple sorts below its own pre-releases too
        limit = self.partial_limit()
        if limit is not None:
            if operator == "=":
                return req_tuple <= test_tuple < limit
            if operator == "<=":
                return test_tuple < limit
            if operator == ">":
                return test_tuple >= limit

        if operator == ">=":
            return test_tuple >= req_tuple
        elif operator == "<=":
            return test_tuple <= req_tuple
        elif operator == ">":
            return test_tuple > req_tuple
        elif operator == "<":
            return test_tuple < req_tuple
        elif operator == "=":
            return test_tuple == req_tuple
        else:
            return False


def validate_version(version_req, version) -> bool:
    """
    Return true if version satisfies the version requirement.
    Handles multiple requirements (">= 1.2, < 1.5"), comparison operators, caret (^) and tilde (~) requirements.
    A bare version string is comparable to a caret operator (semver comparison).
    If version is not semver-like, it must match the requirement exactly.
    As with Cargo and npm, a pre-release only satisfies requirements that
    name a pre-release of the same major, minor and fix version.
    """
    expected = str(version_req).strip()
    test = str(version).strip()
    if not TOSCAVersionProperty.is_valid(test):
        # non semver-like version strings must match exactly
        return expected == test

    test_version = TOSCAVersionProperty(test.strip())
    # Split multiple requirements by comma
    requirements = [req.strip() for req in expected.split(",")]

    if test_version.pre_release and not any(
        _names_pre_release_of(req, test_version) for req in requirements
    ):
        return False

    # All requirements must be satisfied
    for req in requirements:
        if not _evaluate_requirement(req, test_version):
            return False

    return True


def _names_pre_release_of(requirement, version) -> bool:
    """Whether ``requirement`` names a pre-release of ``version``'s major,
    minor and fix version."""
    req_version = TOSCAVersionProperty(requirement.lstrip("<>=").strip())
    return bool(req_version.pre_release) and (
        req_version.version_tuple() == version.version_tuple()
    )


def _evaluate_requirement(expected, test_version) -> bool:
    """Evaluate a version requirement against the test version."""
    # Check for comparison operators
    for op in [">=", "<=", ">", "<", "="]:
        if expected.startswith(op):
            req_version = TOSCAVersionProperty(expected[len(op) :].strip())
            return req_version.compare_version(test_version, op)

    # Check for tilde requirement
    if expected.startswith("~"):
        req_version = TOSCAVersionProperty(expected)
        return req_version.has_minimum_version(test_version)

    # Caret requirement (default) or exact
    req_version = TOSCAVersionProperty(expected)
    # the limit, a 3-tuple, sorts below its own pre-releases too
    limit = req_version.caret_limit()
    return req_version.precedence() <= test_version.precedence() < limit
