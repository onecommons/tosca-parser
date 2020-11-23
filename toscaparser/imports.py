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
import os

from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import InvalidPropertyValueError
from toscaparser.common.exception import MissingRequiredFieldError
from toscaparser.common.exception import UnknownFieldError
from toscaparser.common.exception import ValidationError
from toscaparser.elements.tosca_type_validation import TypeValidation
from toscaparser.utils.gettextutils import _
import toscaparser.utils.urlutils
import toscaparser.utils.yamlparser
from six.moves.urllib.parse import urlparse

YAML_LOADER = toscaparser.utils.yamlparser.load_yaml
log = logging.getLogger("tosca")

class ImportResolver(object):
    def get_url(self, importsLoader, repository_name, file_name, isFile=None):
        if repository_name:
            repo_def = importsLoader.repositories[repository_name]
            full_url = repo_def['url'].strip()
            if file_name:
                full_url = full_url.rstrip("/") + "/" + file_name
        else:
            full_url = file_name
        if isFile:
            return full_url, True, None

        parsed = urlparse(full_url)
        if parsed.scheme == 'file':
            path = parsed.path
            if importsLoader.path:
                path = os.path.join(importsLoader.path, path)
            return path, True, parsed.fragment
        if toscaparser.utils.urlutils.UrlUtils.validate_url(full_url):
            return full_url, False, None
        else:
            return None

    def load_yaml(self, importsLoader, path, isFile=True, fragment=None):
        return YAML_LOADER(path, isFile, importsLoader, fragment)

class ImportsLoader(object):

    IMPORTS_SECTION = (FILE, REPOSITORY, NAMESPACE_URI, NAMESPACE_PREFIX) = \
                      ('file', 'repository', 'namespace_uri',
                       'namespace_prefix')

    def __init__(self, importslist, path, type_definition_list=None,
                 tpl=None, resolver=None):
        self.importslist = importslist
        self.custom_defs = {}
        self.nested_tosca_tpls = []
        self.nested_imports = {}
        self.resolver = resolver or ImportResolver()
        if not path and not tpl:
            msg = _('Input tosca template is not provided.')
            log.warning(msg)
            ExceptionCollector.appendException(ValidationError(message=msg))
        self.path = path
        self.repositories = (tpl and tpl.get('repositories')) or {}
        self.tpl = tpl
        self.type_definition_list = []
        if type_definition_list:
            if isinstance(type_definition_list, list):
                self.type_definition_list = type_definition_list
            else:
                self.type_definition_list.append(type_definition_list)
        if importslist is not None:
            self._validate_and_load_imports()

    def get_custom_defs(self):
        return self.custom_defs

    def get_nested_tosca_tpls(self):
        return self.nested_tosca_tpls

    def get_nested_imports(self):
        return self.nested_imports

    def _validate_and_load_imports(self):
        imports_names = set()

        if not self.importslist:
            msg = _('"imports" keyname is defined without including '
                    'templates.')
            log.error(msg)
            ExceptionCollector.appendException(ValidationError(message=msg))
            return

        for import_def in self.importslist:
            if isinstance(import_def, dict):
                if len(import_def) == 1 and 'file' not in import_def:
                    # old style
                    import_name, import_uri = list(import_def.items())[0]
                    if import_name in imports_names:
                        msg = (_('Duplicate import name "%s" was found.') %
                               import_name)
                        log.error(msg)
                        ExceptionCollector.appendException(
                            ValidationError(message=msg))
                    imports_names.add(import_name)
                else:
                    import_name = None
                    import_uri = import_def

                full_file_name, custom_type = self._load_import_template(
                    import_name, import_uri)
                namespace_prefix = None
                if isinstance(import_uri, dict):
                    namespace_prefix = import_uri.get(
                        self.NAMESPACE_PREFIX)
                if custom_type:
                    TypeValidation(custom_type, import_def)
                    self._update_custom_def(custom_type, namespace_prefix)
            else:  # import_def is just the uri string
                full_file_name, custom_type = self._load_import_template(
                    None, import_def)
                if custom_type:
                    TypeValidation(
                        custom_type, import_def)
                    self._update_custom_def(custom_type, None)

            if custom_type and 'imports' in custom_type.keys():
                self.nested_imports.update(
                    {full_file_name: custom_type['imports']})
            self._update_nested_tosca_tpls(full_file_name, custom_type)

    def _update_custom_def(self, custom_type, namespace_prefix):
        for type_def in self.type_definition_list:
            outer_custom_types = custom_type.get(type_def)
            if outer_custom_types:
                if type_def == "imports":
                    for i in self.custom_defs.get('imports', []):
                        if i not in outer_custom_types:
                            outer_custom_types.append(i)
                    self.custom_defs.update({'imports': outer_custom_types})
                else:
                    if type_def in ['node_types', 'relationship_types']:
                        for custom_def in outer_custom_types.values():
                            custom_def['_source'] = self.path
                    if namespace_prefix:
                        prefix_custom_types = {}
                        for type_def_key in outer_custom_types:
                            namespace_prefix_to_key = (namespace_prefix +
                                                       "." + type_def_key)
                            prefix_custom_types[namespace_prefix_to_key] = \
                                outer_custom_types[type_def_key]
                        self.custom_defs.update(prefix_custom_types)
                    else:
                        self.custom_defs.update(outer_custom_types)

    def _update_nested_tosca_tpls(self, full_file_name, custom_tpl):
        if full_file_name and custom_tpl:
            topo_tpl = {full_file_name: custom_tpl}
            self.nested_tosca_tpls.append(topo_tpl)

    def _validate_import_keys(self, import_name, import_uri_def):
        if self.FILE not in import_uri_def.keys():
            log.warning(_('Missing keyname "file" in import "%(name)s".')
                        % {'name': import_name})
            ExceptionCollector.appendException(
                MissingRequiredFieldError(
                    what='Import of template "%s"' % import_name,
                    required=self.FILE))
        for key in import_uri_def.keys():
            if key not in self.IMPORTS_SECTION:
                log.warning(_('Unknown keyname "%(key)s" error in '
                              'imported definition "%(def)s".')
                            % {'key': key, 'def': import_name})
                ExceptionCollector.appendException(
                    UnknownFieldError(
                        what='Import of template "%s"' % import_name,
                        field=key))

    def _load_import_template(self, import_name, import_uri_def):
        """Handle custom types defined in imported template files

        This method loads the custom type definitions referenced in "imports"
        section of the TOSCA YAML template by determining whether each import
        is specified via a file reference (by relative or absolute path) or a
        URL reference.

        Possibilities:
        +----------+--------+------------------------------+
        | template | import | comment                      |
        +----------+--------+------------------------------+
        | file     | file   | OK                           |
        | file     | URL    | OK                           |
        | preparsed| file   | file must be a full path     |
        | preparsed| URL    | OK                           |
        | URL      | file   | file must be a relative path |
        | URL      | URL    | OK                           |
        +----------+--------+------------------------------+
        """
        path, a_file, fragment = self._resolve_import_template(import_name, import_uri_def)
        if path is not None:
            doc = self.resolver.load_yaml(self, path, a_file, fragment)
            return getattr(doc, "path", path), doc
        else:
            return None, None

    def _resolve_import_template(self, import_name, import_uri_def):
        short_import_notation = False
        if isinstance(import_uri_def, dict):
            self._validate_import_keys(import_name, import_uri_def)
            file_name = import_uri_def.get(self.FILE)
            repository = import_uri_def.get(self.REPOSITORY)
            repos = self.repositories.keys()
            if repository is not None:
                if repository not in repos:
                    ExceptionCollector.appendException(
                        InvalidPropertyValueError(
                            what=_('Repository is not found in "%s"') % repos))
                    return None, None, None
        else:
            file_name = import_uri_def
            repository = None
            short_import_notation = True

        if file_name is None:
            msg = (_('A template file name is not provided with import '
                     'definition "%(import_name)s".')
                   % {'import_name': import_name})
            log.error(msg)
            ExceptionCollector.appendException(ValidationError(message=msg))
            return None, None, None

        if toscaparser.utils.urlutils.UrlUtils.validate_url(file_name):
            # it's an absolute URL
            return self.resolver.get_url(self, repository, file_name, False)
        elif not repository:
            fragment = None
            import_template = None
            if self.path:
                if toscaparser.utils.urlutils.UrlUtils.validate_url(self.path):
                    if os.path.isabs(file_name):
                        msg = (_('Absolute file name "%(name)s" cannot be '
                                 'used in a URL-based input template '
                                 '"%(template)s".')
                               % {'name': file_name, 'template': self.path})
                        log.error(msg)
                        ExceptionCollector.appendException(ImportError(msg))
                        return None, None
                    import_template = toscaparser.utils.urlutils.UrlUtils.\
                        join_url(self.path, file_name)
                    assert import_template
                    a_file = False
                else:
                    a_file = True
                    main_a_file = os.path.isfile(self.path)
                    if '#' in file_name:
                        file_name, sep, fragment = file_name.rpartition('#')
                    if os.path.isabs(file_name):
                        import_template = file_name
                    elif os.path.isdir(self.path):
                        import_template = os.path.join(self.path, file_name)
                    elif main_a_file:
                        if os.path.isfile(file_name):
                            import_template = file_name
                        else:
                            full_path = os.path.join(
                                os.path.dirname(os.path.abspath(self.path)),
                                file_name)
                            if os.path.isfile(full_path):
                                import_template = full_path
                            else:
                                file_path = file_name.rpartition(os.path.sep)
                                dir_path = os.path.dirname(os.path.abspath(
                                    self.path))
                                if file_path[0] != '' and dir_path.endswith(
                                        file_path[0]):
                                        import_template = os.path.join(dir_path,
                                            file_path[2])
                                        if not os.path.isfile(import_template):
                                            msg = (_('"%(import_template)s" is'
                                                     'not a valid file')
                                                   % {'import_template':
                                                      import_template})
                                            log.error(msg)
                                            ExceptionCollector.appendException
                                            (ValueError(msg))
                                else:
                                    import_template = full_path #try anyway

            else:  # template is pre-parsed
                if os.path.isabs(file_name) and os.path.isfile(file_name):
                    a_file = True
                    import_template = file_name
                else:
                    msg = (_('Relative file name "%(name)s" cannot be used '
                             'in a pre-parsed input template.')
                           % {'name': file_name})
                    log.error(msg)
                    ExceptionCollector.appendException(ImportError(msg))
                    return None, None, None

            if not import_template:
                ExceptionCollector.appendException(
                    ImportError(_('Import "%s" is not valid.') %
                                import_uri_def))
                return None, None, None

            url_info = self.resolver.get_url(self, repository, import_template, a_file)
            if not url_info:
                log.error(_('Import "%s" is not valid.') % import_uri_def)
                ExceptionCollector.appendException(
                    ImportError(_('Import "%s" is not valid.') % import_uri_def))
                return None, None, None
            return url_info[0], url_info[1], fragment

        if short_import_notation:
            log.error(_('Import "%s" is not valid.') % import_uri_def)
            ExceptionCollector.appendException(
                ImportError(_('Import "%s" is not valid.') % import_uri_def))
            return None, None, None

        assert repository
        return self._resolve_from_repository(repository, import_name, file_name)

    def _resolve_from_repository(self, repository, import_name, file_name):
        url_info = self.resolver.get_url(self, repository, file_name)
        if not url_info:
            msg = (_('repository url "%(n_uri)s" is not valid in import '
                     'definition "%(tpl)s".')
                   % {'n_uri': self.repositories[repository]['url'], 'tpl': import_name})
            log.error(msg)
            ExceptionCollector.appendException(ImportError(msg))
            return None, None, None
        return url_info
