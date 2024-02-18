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
from typing import Optional

from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import FatalToscaImportError
from toscaparser.common.exception import MissingRequiredFieldError
from toscaparser.common.exception import UnknownFieldError
from toscaparser.common.exception import ValidationError
from toscaparser.common.exception import URLException
from toscaparser.elements.entity_type import EntityType, Namespace
from toscaparser.elements.tosca_type_validation import TypeValidation
from toscaparser.utils.gettextutils import _
import toscaparser.utils.urlutils
import toscaparser.utils.yamlparser
from toscaparser.repositories import Repository

try:
    from typing import TypedDict

    class SourceInfo(TypedDict):
        path: str  # local path to this imported file
        repository: Optional[str]  # repository name if specified in the import
        root: Optional[str]  # URL of repository or path to root service template
        file: str  # file path relative to root (with fragment if present)
        namespace_uri: Optional[str]  # "namespace" field in source file

except ImportError:
    SourceInfo = dict  # Python 3.7


YAML_LOADER = toscaparser.utils.yamlparser.load_yaml
log = logging.getLogger("tosca")

TREAT_IMPORTS_AS_FATAL = True


def is_url(url):
    return toscaparser.utils.urlutils.UrlUtils.validate_url(url)


def normalize_path(path):
    "Convert file URLs to paths and expand user"
    if path.startswith("file:"):
        path = path[len("file:") :]
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


class ImportResolver:
    """
    Callback interface for integration with an TOSCA orchestrator.
    """

    def get_repository(self, name, tpl):
        return Repository(name, tpl)

    def get_repository_url(self, importsLoader, repository_name, package=None):
        if package:
            return package.get("namespace_uri") or package["path"]
        if repository_name:
            repo_def = importsLoader.repositories[repository_name]
            url = repo_def["url"].strip()
            return normalize_path(url)
        else:
            return ""

    def resolve_url(self, importsLoader, base, file_name, repository_name):
        if is_url(base) and not repository_name:
            # urls will not have had file component stripped (defer to the resolver implementation)
            base = os.path.dirname(base)
        path = os.path.join(base, file_name)
        return path, not is_url(path)

    def load_yaml(self, path, fragment, ctx):
        isFile = ctx
        return YAML_LOADER(path, isFile, fragment), None

    def load_imports(self, importsLoader, importslist):
        importsLoader.importslist = importslist
        importsLoader._validate_and_load_imports()
        return importsLoader.get_custom_defs()

    def find_matching_node(self, relTpl, req_name, req_def):
        if relTpl.target:
            return relTpl.target, relTpl.capability
        return None, None

    def find_implementation(self, op):
        return None

    def find_repository_path(self, name, tpl=None, base_path=None):
        return None

    def get_safe_mode(self):
        return False


class ImportsLoader(object):
    IMPORTS_SECTION = (FILE, REPOSITORY, NAMESPACE_URI, NAMESPACE_PREFIX, WHEN) = (
        "file",
        "repository",
        "namespace_uri",
        "namespace_prefix",
        "when",
    )

    def __init__(
        self,
        importslist,
        path,
        namespace=None,
        repositories=None,
        resolver=None,
        repository_root=None,
    ):
        self.importslist = importslist
        self.custom_defs = Namespace({}, None) if namespace is None else namespace
        self.nested_tosca_tpls = {}
        self.resolver = resolver or ImportResolver()
        self.repository_root = None
        if repository_root is not None:
            if not is_url(normalize_path(repository_root)):
                repository_root = get_base(repository_root)
            self.repository_root = repository_root
        self.path = path
        self.repositories = repositories or {}
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

            imported_types, prefix = self._load_import(import_def, import_name)
            if imported_types and imported_types is not self.custom_defs:
                # add the imported types that are in a separate namespace
                self.custom_defs.add_with_prefix(imported_types, prefix)

    def _load_import(self, import_def, import_name):
        base, full_file_name, imported_tpl = self.load_yaml(import_def, import_name)
        if full_file_name is None:
            if TREAT_IMPORTS_AS_FATAL:
                self.abort(import_def)
            return None, None

        namespace_prefix = None
        repository_name = None
        if isinstance(import_def, dict):
            namespace_prefix = import_def.get(self.NAMESPACE_PREFIX)
            repository_name = import_def.get(self.REPOSITORY)
            file_name = import_def.get(self.FILE)
        else:
            file_name = import_def

        if not is_url(full_file_name):
            full_file_name = os.path.normpath(full_file_name)

        root_path = base if repository_name else self.repository_root
        declared_namespace_id = imported_tpl and imported_tpl.get("namespace") or None
        if not declared_namespace_id and self.custom_defs.shared_namespace:
            # if current namespace is global use that one
            declared_namespace_id = self.custom_defs.namespace_id
        _source, namespace_id = self.get_source(
            root_path, full_file_name, repository_name, file_name, declared_namespace_id
        )
        # resolver could have changed this
        declared_namespace_id = _source.get("namespace_uri")

        if full_file_name and imported_tpl:
            if (
                full_file_name in self.nested_tosca_tpls
                and namespace_id in self.custom_defs.all_namespaces
            ):
                # already imported
                return self.custom_defs.all_namespaces[namespace_id], namespace_prefix
            self.nested_tosca_tpls[full_file_name] = (imported_tpl, namespace_id)

        if namespace_id in self.custom_defs.all_namespaces:
            imported_types = self.custom_defs.all_namespaces[namespace_id]
        else:
            imported_types = Namespace(
                self.custom_defs.all_namespaces,
                _source,
                namespace_id,
                bool(declared_namespace_id),
            )

        if imported_tpl:
            imports = imported_tpl.get("imports")
            if imports:
                imports_loader = ImportsLoader(
                    None,
                    full_file_name,
                    imported_types,
                    self.repositories,
                    self.resolver,
                    root_path,
                )
                imports_loader.resolver.load_imports(imports_loader, imports)
                self.nested_tosca_tpls.update(imports_loader.nested_tosca_tpls)

            TypeValidation(imported_tpl, import_def)
            local_types = self._update_custom_def(imported_tpl, imported_types, True)
            imported_types.update(local_types)
        return imported_types, namespace_prefix

    def get_source(self, root_path, path, repository_name, file_name, namespace_uri):
        # return enough metadata so we can reconstruct an imports declaration for this namespace
        _source = SourceInfo(
            path=path,  # path to this imported file
            root=root_path,  # repository or service template url
            repository=repository_name,  # repository name if specified in the import
            file=file_name,  # file path relative to root (with fragment if present)
            # namespace_uri will be null if namespace is not an explicit namespace
            namespace_uri=namespace_uri,  # namespace field if declared
        )
        # if not repository_name return package_id for the root template
        namespace_id = self.resolver.get_repository_url(self, repository_name, _source)
        return _source, namespace_id

    def abort(self, import_def):
        import_repr = (
            import_def
            if isinstance(import_def, (str, type(None))) or not import_def.get("file")
            else import_def["file"]
        )
        error = FatalToscaImportError(
            message=f'Aborting parsing of service template: can not import "{import_repr}"'
        )
        if ExceptionCollector.exceptions:
            error.__cause__ = ExceptionCollector.exceptions[-1]
        raise error

    def _update_custom_def(self, imported_tpl, namespace, add_source_info):
        for type_def_section in EntityType.TOSCA_DEF_SECTIONS:
            outer_custom_types = imported_tpl.get(type_def_section)
            if outer_custom_types:
                if add_source_info and type_def_section in [
                    "node_types",
                    "relationship_types",
                    "artifact_types",
                    "data_types",
                    "capability_types",
                ]:
                    for name, custom_def in outer_custom_types.items():
                        custom_def["_source"] = dict(
                            namespace.source_info,
                            section=type_def_section,
                            local_name=name,
                            namespace_id=namespace.namespace_id,
                        )
                namespace.update(outer_custom_types)
        return namespace

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
            path = url_info
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
        repository_name, file_name = self._resolve_import_template(
            import_name, import_uri_def
        )
        if file_name is None:
            return None
        file_name, sep, fragment = file_name.partition("#")
        path = normalize_path(file_name)
        doc_base = self.path if is_url(self.path) else get_base(self.path)
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
            path, ctx = self.resolver.resolve_url(
                self, base, os.path.normpath(path), repository_name
            )
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
                            message=_('Unknown repository in import "%s"')
                            % import_uri_def
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
