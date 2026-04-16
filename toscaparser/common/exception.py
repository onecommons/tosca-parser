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

'''
TOSCA exception classes
'''
import logging
import sys
import traceback

from toscaparser.utils.gettextutils import _


log = logging.getLogger(__name__)


class TOSCAException(Exception):
    '''Base exception class for TOSCA

    To correctly use this class, inherit from it and define
    a 'msg_fmt' property.

    '''

    _FATAL_EXCEPTION_FORMAT_ERRORS = False

    message = _('An unknown exception occurred.')

    def __init__(self, **kwargs):
        try:
            self.message = self.msg_fmt % kwargs
            self.near = ExceptionCollector.near
        except KeyError:
            exc_info = sys.exc_info()
            log.exception('Exception in string format operation: %s'
                          % exc_info[1])

            if TOSCAException._FATAL_EXCEPTION_FORMAT_ERRORS:
                raise exc_info[0]

    def __str__(self):
        return self.message

    @staticmethod
    def generate_inv_schema_property_error(self, attr, value, valid_values):
        msg = (_('Schema definition of "%(propname)s" has '
                 '"%(attr)s" attribute with invalid value '
                 '"%(value1)s". The value must be one of '
                 '"%(value2)s".') % {"propname": self.name,
                                     "attr": attr,
                                     "value1": value,
                                     "value2": valid_values})
        ExceptionCollector.appendException(
            InvalidSchemaError(message=msg))

    @staticmethod
    def set_fatal_format_exception(flag):
        if isinstance(flag, bool):
            TOSCAException._FATAL_EXCEPTION_FORMAT_ERRORS = flag


class UnsupportedTypeError(TOSCAException):
    msg_fmt = _('Type "%(what)s" is valid TOSCA type'
                ' but not supported at this time.')


class MissingRequiredFieldError(TOSCAException):
    msg_fmt = _('%(what)s is missing required field "%(required)s".')


class UnknownFieldError(TOSCAException):
    msg_fmt = _('%(what)s contains unknown field "%(field)s". Refer to the '
                'definition to verify valid values.')


class TypeMismatchError(TOSCAException):
    msg_fmt = _('%(what)s must be of type "%(type)s".')


class InvalidNodeTypeError(TOSCAException):
    msg_fmt = _('Node type "%(what)s" is not a valid type.')


class InvalidTypeError(TOSCAException):
    msg_fmt = _('Type "%(what)s" is not a valid type.')

class InvalidTypeDefinition(TOSCAException):
    msg_fmt = _('Type "%(type)s" is not a valid type: %(what)s.')

class MissingTypeError(TOSCAException):
    msg_fmt = _('No definition for type "%(what)s" found.')


class InvalidTypeAdditionalRequirementsError(TOSCAException):
    msg_fmt = _('Additional requirements for type "%(type)s" not met.')


class RangeValueError(TOSCAException):
    msg_fmt = _('The value "%(pvalue)s" of property "%(pname)s" is out of '
                'range "(min:%(vmin)s, max:%(vmax)s)".')


class InvalidSchemaError(TOSCAException):
    msg_fmt = _('%(message)s')


class ValidationError(TOSCAException):
    msg_fmt = _('%(message)s')


class UnknownInputError(TOSCAException):
    msg_fmt = _('Unknown input "%(input_name)s".')


class UnknownOutputError(TOSCAException):
    msg_fmt = _('Unknown output "%(output_name)s" in %(where)s.')


class MissingRequiredInputError(TOSCAException):
    msg_fmt = _('%(what)s is missing required input definition '
                'of input "%(input_name)s".')


class MissingRequiredParameterError(TOSCAException):
    msg_fmt = _('%(what)s is missing required parameter for input '
                '"%(input_name)s".')


class MissingDefaultValueError(TOSCAException):
    msg_fmt = _('%(what)s is missing required default value '
                'of input "%(input_name)s".')


class MissingRequiredOutputError(TOSCAException):
    msg_fmt = _('%(what)s is missing required output definition '
                'of output "%(output_name)s".')


class InvalidPropertyValueError(TOSCAException):
    msg_fmt = _('Value of property "%(what)s" is invalid.')


class InvalidOccurrences(TOSCAException):
    msg_fmt = _('Value "%(what)s" of "occurrences" is invalid: %(why)s.')


class InvalidTemplateVersion(TOSCAException):
    msg_fmt = _('The template version "%(what)s" is invalid. '
                'Valid versions are "%(valid_versions)s".')


class InvalidTOSCAVersionPropertyException(TOSCAException):
    msg_fmt = _('Value of TOSCA version property "%(what)s" is invalid.')


class URLException(TOSCAException):
    msg_fmt = _('%(what)s')

class FatalToscaImportError(TOSCAException):
    msg_fmt = _('%(message)s')

class ToscaExtImportError(TOSCAException):
    msg_fmt = _('Unable to import extension "%(ext_name)s". '
                'Check to see that it exists and has no '
                'language definition errors.')


class ToscaExtAttributeError(TOSCAException):
    msg_fmt = _('Missing attribute in extension "%(ext_name)s". '
                'Check to see that it has required attributes '
                '"%(attrs)s" defined.')


class InvalidGroupTargetException(TOSCAException):
    msg_fmt = _('"%(message)s"')


class ExceptionCollector(object):

    exceptions = []
    collecting = False
    near = None
    previous = False

    @staticmethod
    def clear():
        del ExceptionCollector.exceptions[:]
        ExceptionCollector.near = None

    @staticmethod
    def start():
        ExceptionCollector.clear()
        ExceptionCollector.collecting = True

    @staticmethod
    def stop():
        ExceptionCollector.collecting = False
        ExceptionCollector.near = None

    @staticmethod
    def pause():
        ExceptionCollector.previous = ExceptionCollector.collecting
        ExceptionCollector.collecting = False

    @staticmethod
    def resume():
        ExceptionCollector.collecting = ExceptionCollector.previous

    @staticmethod
    def contains(exception):
        for ex in ExceptionCollector.exceptions:
            if str(ex) == str(exception):
                return True
        return False

    @staticmethod
    def appendException(exception):
        if ExceptionCollector.collecting:
            if not ExceptionCollector.contains(exception):
                # extract_stack()[:-1] drops this appendException frame itself.
                # The next frame up is the caller that raised the error — keep
                # its file/line/method but blank its call source since that
                # source is always the `ExceptionCollector.appendException(...)`
                # line, which is redundant noise in every report.
                stack = traceback.extract_stack()[:-1]
                if stack:
                    last = stack[-1]
                    stack[-1] = traceback.FrameSummary(
                        last.filename, last.lineno, last.name, line=""
                    )
                exception.trace = stack
                ExceptionCollector.exceptions.append(exception)
                log.debug('\n'.join(ExceptionCollector.getExceptionReportEntry(exception, False)))
        else:
            raise exception

    @staticmethod
    def exceptionsCaught():
        return len(ExceptionCollector.exceptions) > 0

    @staticmethod
    def getTraceString(traceList):
        traceString = ''
        if traceList:
          for entry in traceList:
              f, l, m, c = entry[0], entry[1], entry[2], entry[3]
              traceString += (_('\t\tFile %(file)s, line %(line)s, in '
                                '%(method)s\n')
                              % {'file': f, 'line': l, 'method': m})
              if c:
                  traceString += _('\t\t\t%(call)s\n') % {'call': c}
        return traceString

    @staticmethod
    def getExceptionReportEntry(exception, full=True, extra=True):
        """Return a list of lines/blocks describing the exception.

        The list is ordered from most essential to most verbose:
          [0]  "ClassName: message" (with `near` appended if extra=True)
          [1]  "Caused by: ..." line (only if __cause__ is set)
          next the stack trace (only if full=True)
          then the cause's entries, recursively flattened (only if full=True)
        """
        summary = exception.__class__.__name__ + ': ' + str(exception)
        if extra and getattr(exception, 'near', None):
            summary += exception.near
        entries = [summary]
        if exception.__cause__:
            entries.append(
                f"Caused by:{exception.__cause__.__class__.__name__}:{exception.__cause__}"
            )
        if full:
            entries.append(ExceptionCollector.getTraceString(exception.trace))
            if exception.__cause__:
                cause = exception.__cause__
                if cause.__traceback__:
                    cause.trace = traceback.extract_tb(cause.__traceback__)[:-1]
                else:
                    cause.trace = ()
                entries.extend(
                    ExceptionCollector.getExceptionReportEntry(cause, full, extra)
                )
        return entries



    @staticmethod
    def getExceptions():
        return ExceptionCollector.exceptions

    @staticmethod
    def getExceptionsReport(full=True, extra=True):
        """Return a list of strings, one per collected exception.

        ``full`` controls verbosity:
          * ``True``  — everything (summary + cause line + full trace + nested cause entries)
          * ``False`` — summary + cause line only (no trace)
          * ``int N`` (non-bool, ``> 0``) — summary followed by the last ``N``
            lines of the exception's stack trace.
        """
        # bool is a subclass of int, so test for bool too
        trace_tail = isinstance(full, int) and not isinstance(full, bool)
        report = []
        for exception in ExceptionCollector.exceptions:
            if trace_tail and full:
                pieces = ExceptionCollector._format_trace_tail(
                    exception, full, extra
                )
                report.append('\n'.join(pieces))
            else:
                report.append(
                    '\n'.join(
                        ExceptionCollector.getExceptionReportEntry(
                            exception, full, extra
                        )
                    )
                )
        return report

    @staticmethod
    def _format_trace_tail(exception, n, extra):
        """Summary line + last ``n`` lines of the stack trace, recursing
        through ``__cause__`` so each level's summary + trimmed trace is
        included."""
        summary = exception.__class__.__name__ + ': ' + str(exception)
        if extra and getattr(exception, 'near', None):
            summary += exception.near
        pieces = [summary]
        trace_lines = ExceptionCollector.getTraceString(
            getattr(exception, 'trace', None)
        ).splitlines()
        if trace_lines:
            pieces.extend(trace_lines[-n:])
        cause = exception.__cause__
        if cause is not None:
            if getattr(cause, 'trace', None) is None:
                if cause.__traceback__:
                    cause.trace = traceback.extract_tb(cause.__traceback__)[:-1]
                else:
                    cause.trace = ()
            pieces.append(
                f"Caused by:{cause.__class__.__name__}:{cause}"
            )
            cause_trace = ExceptionCollector.getTraceString(
                cause.trace
            ).splitlines()
            if cause_trace:
                pieces.extend(cause_trace[-n:])
        return pieces

    @staticmethod
    def assertExceptionMessage(exception, message):
        err_msg = exception.__name__ + ': ' + message
        report = ExceptionCollector.getExceptionsReport(False, False)
        assert err_msg in report, (_('Could not find "%(msg)s" in "%(rep)s".')
                                   % {'rep': report.__str__(), 'msg': err_msg})
