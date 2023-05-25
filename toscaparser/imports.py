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
from toscaparser.common.exception import URLException
from toscaparser.elements.tosca_type_validation import TypeValidation
from toscaparser.utils.gettextutils import _
import toscaparser.utils.urlutils
import toscaparser.utils.yamlparser
from six.moves.urllib.parse import urlparse
from toscaparser.repositories import Repository


YAML_LOADER = toscaparser.utils.yamlparser.load_yaml
log = logging.getLogger("tosca")


class ImportResolver(object):
    def get_repository(self, name, tpl):
        return Repository(name, tpl)

    def get_repository_url(self, importsLoader, repository_name):
        repo_def = importsLoader.repositories[repository_name]
        url = repo_def["url"].strip()
        if url.startswith("file:") and importsLoader:
            url_path = url[5:]
            # its relative so join with current location of import
            if not os.path.isabs(url_path) and importsLoader.path:
                if os.path.isdir(importsLoader.path):
                    base_path = importsLoader.path
                else:
                    base_path = os.path.dirname(importsLoader.path)
                return "file://" + os.path.join(base_path, url_path)

        return url

    def get_url(self, importsLoader, repository_name, file_name, isFile=None):
        if repository_name:
            full_url = self.get_repository_url(importsLoader, repository_name)
            if file_name:
                full_url = full_url.rstrip("/") + "/" + file_name
        else:
            full_url = file_name
        if isFile:
            return full_url, True, None

        parsed = urlparse(full_url)
        if parsed.scheme == "file":
            path = parsed.path
            if importsLoader.path:
                if os.path.isdir(importsLoader.path):
                    base_path = importsLoader.path
                else:
                    base_path = os.path.dirname(importsLoader.path)
                path = os.path.join(base_path, path)
            return path, True, parsed.fragment
        if toscaparser.utils.urlutils.UrlUtils.validate_url(full_url):
            return full_url, False, None
        else:
            return None

    def load_yaml(self, importsLoader, path, isFile=True, fragment=None):
        return YAML_LOADER(path, isFile, importsLoader, fragment)

    def load_imports(self, importsLoader, importslist):
        importsLoader.importslist = importslist
        importsLoader._validate_and_load_imports()


class ImportsLoader(object):

    IMPORTS_SECTION = (FILE, REPOSITORY, NAMESPACE_URI, NAMESPACE_PREFIX, WHEN) = (
        "file",
        "repository",
        "namespace_uri",
        "namespace_prefix",
        "when",
    )

    def __init__(
        self, importslist, path, type_definition_list=None, repositories=None, resolver=None
    ):
        self.importslist = importslist
        self.custom_defs = {}
        self.nested_tosca_tpls = []
        self.resolver = resolver or ImportResolver()
        self.path = path
        self.repositories = repositories or {}
        # names of type definition sections
        self.type_definition_list = type_definition_list or []
        if importslist is not None:
            if not path:
                msg = _("Input tosca template is not provided.")
                log.warning(msg)
                ExceptionCollector.appendException(ValidationError(message=msg))
            self._validate_and_load_imports()

    def get_custom_defs(self):
        return self.custom_defs

    def get_nested_tosca_tpls(self):
        return self.nested_tosca_tpls

    def _validate_and_load_imports(self):
        imports_names = set()

        if not self.importslist:
            msg = _('"imports" keyname is defined without including ' "templates.")
            log.error(msg)
            ExceptionCollector.appendException(ValidationError(message=msg))
            return

        for import_tpl in self.importslist:
            if isinstance(import_tpl, dict):
                if len(import_tpl) == 1 and "file" not in import_tpl:
                    # old style {name: uri}
                    import_name, import_def = list(import_tpl.items())[0]
                    if import_name in imports_names:
                        msg = _('Duplicate import name "%s" was found.') % import_name
                        log.error(msg)
                        ExceptionCollector.appendException(ValidationError(message=msg))
                    imports_names.add(import_name)
                else:  # new style {"file": uri}
                    import_name = None
                    import_def = import_tpl

            else:  # import_def is just the uri string
                import_name = None
                import_def = import_tpl

            full_file_name, imported_tpl = self.load_yaml(import_def, import_name)
            if full_file_name is None:
                return

            namespace_prefix = None
            if isinstance(import_def, dict):
                namespace_prefix = import_def.get(self.NAMESPACE_PREFIX)
            if imported_tpl:
                TypeValidation(imported_tpl, import_tpl)
                self._update_custom_def(imported_tpl, namespace_prefix, full_file_name)
            # XXX should save prefix too
            self._update_nested_tosca_tpls(full_file_name, imported_tpl)

    def _update_custom_def(self, imported_tpl, namespace_prefix, path):
        path = os.path.normpath(path)
        for type_def_section in self.type_definition_list:
            outer_custom_types = imported_tpl.get(type_def_section)
            if outer_custom_types:
                if type_def_section in [
                    "node_types",
                    "relationship_types",
                    "artifact_types",
                ]:
                    for custom_def in outer_custom_types.values():
                        custom_def["_source"] = path
                if namespace_prefix:
                    prefix_custom_types = {}
                    for type_def_key in outer_custom_types:
                        namespace_prefix_to_key = namespace_prefix + "." + type_def_key
                        prefix_custom_types[
                            namespace_prefix_to_key
                        ] = outer_custom_types[type_def_key]
                    self.custom_defs.update(prefix_custom_types)
                else:
                    self.custom_defs.update(outer_custom_types)

    def _update_nested_tosca_tpls(self, full_file_name, custom_tpl):
        if full_file_name and custom_tpl:
            topo_tpl = {full_file_name: custom_tpl}
            self.nested_tosca_tpls.append(topo_tpl)

    def _validate_import_keys(self, import_name, import_uri_def):
        if self.FILE not in import_uri_def.keys():
            log.warning(
                'Missing keyname "file" in import "%(name)s".' % {"name": import_name}
            )
            ExceptionCollector.appendException(
                MissingRequiredFieldError(
                    what='Import of template "%s"' % import_name, required=self.FILE
                )
            )
        for key in import_uri_def.keys():
            if key not in self.IMPORTS_SECTION:
                log.warning(
                    'Unknown keyname "%(key)s" error in '
                    'imported definition "%(def)s".' % {"key": key, "def": import_name}
                )
                ExceptionCollector.appendException(
                    UnknownFieldError(
                        what='Import of template "%s"' % import_name, field=key
                    )
                )

    def load_yaml(self, import_uri_def, import_name=None):
        path, a_file, fragment = self.resolve_import(import_uri_def, import_name)
        if path is not None:
            try:
                doc = self.resolver.load_yaml(self, path, a_file, fragment)
            except Exception as e:
                msg = _('Import "%s" is not valid.') % path
                url_exc = URLException(what=msg)
                url_exc.__cause__ = e
                ExceptionCollector.appendException(url_exc)
                return None, None
            return getattr(doc, "path", path), doc
        else:
            return None, None

    def resolve_import(self, import_uri_def, import_name=None):
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
        fragment = None
        repository_name, file_name = self._resolve_import_template(import_name, import_uri_def)
        is_url = toscaparser.utils.urlutils.UrlUtils.validate_url(file_name)
        if is_url:
            # it's an absolute URL, ignore repository
            repository_name = None
            is_file = False
        elif repository_name:
            is_file = None  # unknown, depends on repository
        else:
            if self.path:
                file_name, is_file, fragment = self._resolve_to_local_path(file_name)
                if file_name is None:
                    return None, None, None
            else:  # template is pre-parsed
                if file_name and os.path.isabs(file_name):
                    is_file = True
                else:
                    msg = _(
                        'Relative file name "%(name)s" cannot be used '
                        "in a pre-parsed input template."
                    ) % {"name": file_name}
                    log.error(msg)
                    ExceptionCollector.appendException(ImportError(msg))
                    return None, None, None

        url_info = self.resolver.get_url(self, repository_name, file_name, is_file)
        if not url_info:
            msg = _('Import "%s" is not valid.') % import_uri_def
            log.error(msg)
            ExceptionCollector.appendException(ImportError(msg))
            return None, None, None
        return url_info[0], url_info[1], url_info[2] or fragment

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
                        ValidationError(
                            message=_('Repository not found: "%s"') % repository
                        )
                    )
                    return None, None
        else:
            file_name = import_uri_def
            repository = None
            short_import_notation = True

        if file_name is None:
            msg = _(
                "A template file name is not provided with import "
                'definition "%(import_name)s".'
            ) % {"import_name": import_name}
            log.error(msg)
            ExceptionCollector.appendException(ValidationError(message=msg))
        return repository, file_name

    def _resolve_to_local_path(self, file_name):
        fragment = None
        import_template = None
        assert self.path
        is_url = toscaparser.utils.urlutils.UrlUtils.validate_url(self.path)
        if is_url:
            if os.path.isabs(file_name):
                msg = _(
                    'Absolute file name "%(name)s" cannot be '
                    "used in a URL-based input template "
                    '"%(template)s".'
                ) % {"name": file_name, "template": self.path}
                log.error(msg)
                ExceptionCollector.appendException(ImportError(msg))
                return None, None, None
            import_template = toscaparser.utils.urlutils.UrlUtils.join_url(
                self.path, file_name
            )
            assert import_template
        else:
            main_a_file = os.path.isfile(self.path)
            if "#" in file_name:
                file_name, sep, fragment = file_name.rpartition("#")
            if os.path.isabs(file_name):
                import_template = file_name
            elif os.path.isdir(self.path):
                import_template = os.path.join(self.path, file_name)
            elif main_a_file:
                if os.path.isfile(file_name):
                    import_template = file_name
                else:
                    dir_path = os.path.dirname(os.path.abspath(self.path))
                    full_path = os.path.join(dir_path, file_name)
                    if os.path.isfile(full_path):
                        import_template = full_path
                    else:
                        rel_dir, sep, rel_file = file_name.rpartition(os.path.sep)
                        if rel_dir and dir_path.endswith(rel_dir):
                            # if dir parts overlap just try the file part
                            import_template = os.path.join(dir_path, rel_file)
                            if not os.path.isfile(import_template):
                                msg = _(
                                    '"%(import_template)s" is'
                                    "not a valid file"
                                ) % {"import_template": import_template}
                                log.error(msg)
                                ExceptionCollector.appendException
                                (ValueError(msg))
                        else:
                            import_template = full_path  # try anyway
        return import_template, not is_url, fragment
