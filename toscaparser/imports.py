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
from toscaparser.repositories import Repository

YAML_LOADER = toscaparser.utils.yamlparser.load_yaml
log = logging.getLogger("tosca")


def is_url(url):
    return toscaparser.utils.urlutils.UrlUtils.validate_url(url)


def normalize_path(path):
    "Convert file URLs to paths and expand user"
    if path.startswith("file:"):
        path = path[len("file:"):]
        if path and path[0] == "/":
            path = "/" + path.lstrip("/")  # make sure there's only one /
    if path.startswith("~"):
        return os.path.expanduser(path)
    return path


def get_base(path):
    if not path:
        return ""
    path = normalize_path(path)
    if os.path.isdir(path):
        return os.path.abspath(path)
    else:
        path = os.path.dirname(path)
        if not is_url(path):
            return os.path.abspath(path)
        return path


class ImportResolver(object):
    def get_repository(self, name, tpl):
        return Repository(name, tpl)

    def get_repository_url(self, importsLoader, repository_name):
        repo_def = importsLoader.repositories[repository_name]
        url = repo_def["url"].strip()
        path = normalize_path(url)
        return path

    def resolve_url(self, importsLoader, base, file_name, repository_name):
        path = os.path.join(base, file_name)
        return path, not is_url(path)

    def load_yaml(self, path, fragment, ctx):
        isFile = ctx
        return YAML_LOADER(path, isFile, fragment), None

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
        self, importslist, path, type_definition_list=None, repositories=None, resolver=None, repository_root=None,
    ):
        self.importslist = importslist
        self.custom_defs = {}
        self.nested_tosca_tpls = {}
        self.resolver = resolver or ImportResolver()
        self.repository_root = None
        if repository_root is not None:
            if not is_url(normalize_path(repository_root)):
                repository_root = get_base(repository_root)
            self.repository_root = repository_root
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

            base, full_file_name, imported_tpl = self.load_yaml(import_def, import_name)
            if full_file_name is None:
                return

            namespace_prefix = None
            repository_name = None
            if isinstance(import_def, dict):
                namespace_prefix = import_def.get(self.NAMESPACE_PREFIX)
                repository_name = import_def.get(self.REPOSITORY)
                file_name = import_def.get(self.FILE)
            else:
                file_name = import_def

            if imported_tpl:
                TypeValidation(imported_tpl, import_tpl)
                self._update_custom_def(imported_tpl, namespace_prefix, full_file_name,
                                        repository_name, base, file_name)
            root_path = base if repository_name else self.repository_root
            self._update_nested_tosca_tpls(full_file_name, root_path, imported_tpl, namespace_prefix)

    def _update_custom_def(self, imported_tpl, namespace_prefix, path, repository_name, base, file_name):
        path = os.path.normpath(path)
        if repository_name:
            root_path = self.resolver.get_repository_url(self, repository_name)
        else:
            root_path = self.repository_root
        for type_def_section in self.type_definition_list:
            outer_custom_types = imported_tpl.get(type_def_section)
            if outer_custom_types:
                if type_def_section in [
                    "node_types",
                    "relationship_types",
                    "artifact_types",
                ]:
                    for custom_def in outer_custom_types.values():
                        custom_def["_source"] = dict(path=path, prefix=namespace_prefix,
                                                     root=root_path, repository=repository_name,
                                                     base=base, file=file_name)
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

    def _update_nested_tosca_tpls(self, full_file_name, root_path, custom_tpl, namespace_prefix):
        if full_file_name and custom_tpl:
            self.nested_tosca_tpls[full_file_name] = (custom_tpl, root_path, namespace_prefix)

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
        url_info = self.resolve_import(import_uri_def, import_name)
        if url_info is not None:
            try:
                base, path, fragment, ctx = url_info
                doc, ctx = self.resolver.load_yaml(path, fragment, ctx)
            except Exception as e:
                msg = _('Import "%s" is not valid.') % path
                url_exc = URLException(what=msg)
                url_exc.__cause__ = e
                ExceptionCollector.appendException(url_exc)
                return None, None, None
            return base, getattr(doc, "path", path), doc
        else:
            return None, None, None

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
        repository_name, file_name = self._resolve_import_template(import_name, import_uri_def)
        file_name, sep, fragment = file_name.partition("#")
        path = normalize_path(file_name)
        doc_base = get_base(self.path)
        if repository_name:
            if is_url(path) or os.path.isabs(path):
                msg = _(
                    'Absolute URL "%(name)s" cannot be used '
                    'when a repository is specified ("%(repository)s").'
                ) % {"name": file_name, "repository": repository_name}
                ExceptionCollector.appendException(ImportError(msg))
                return None

            base = self.resolver.get_repository_url(self, repository_name)
            if base is None:  # couldn't resolve
                return None
            if self.path and not is_url(base) and not os.path.isabs(base):
                # repository is set to a relative local path
                base = os.path.normpath(os.path.join(doc_base, base))
            path, ctx = self.resolver.resolve_url(self, base, os.path.normpath(path), repository_name)
            if path is None:
                return None
        else:
            base = ""
            if not is_url(path):
                if os.path.isabs(path):
                    if self.path and is_url(self.path):
                        msg = _(
                            'Absolute file name "%(name)s" cannot be '
                            "used in a URL-based input template "
                            '"%(template)s".'
                        ) % {"name": file_name, "template": self.path}
                        ExceptionCollector.appendException(ImportError(msg))
                        return None
                else:
                    # its a relative path
                    path = os.path.normpath(path)
                    if not self.path:
                        msg = _(
                            'Relative file name "%(name)s" cannot be used '
                            "in a pre-parsed input template."
                        ) % {"name": file_name}
                        ExceptionCollector.appendException(ImportError(msg))
                        return None
                    base = doc_base
                    # so join with the current location of import
            path, ctx = self.resolver.resolve_url(self, base, path, repository_name)
            if path is None:
                return None
        return base, path, fragment, ctx

    def _resolve_import_template(self, import_name, import_uri_def):
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

        if file_name is None:
            msg = _(
                "A template file name is not provided with import "
                'definition "%(import_name)s".'
            ) % {"import_name": import_name}
            log.error(msg)
            ExceptionCollector.appendException(ValidationError(message=msg))
        return repository, file_name
