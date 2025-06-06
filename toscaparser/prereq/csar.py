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

import os.path
import requests
import shutil
import tempfile
import yaml
import zipfile

from io import BytesIO

from toscaparser.common.exception import ExceptionCollector
from toscaparser.common.exception import URLException
from toscaparser.common.exception import ValidationError
from toscaparser.imports import ImportsLoader
from toscaparser.utils.gettextutils import _
from toscaparser.utils.urlutils import UrlUtils
from toscaparser.utils import yamlparser


TOSCA_META = 'TOSCA-Metadata/TOSCA.meta'

YAML_LOADER = yamlparser.load_yaml


class CSAR(object):

    def __init__(self, csar_file, a_file=True, unzip_dir=None):
        self.path = csar_file
        self.a_file = a_file
        self.is_validated = False
        self.csar = None
        self.unzip_dir = unzip_dir
        self.is_tosca_metadata = False
        self.main_template_file_name = None
        self.zfile = None

    def validate(self):
        """Validate the provided CSAR file."""

        self.is_validated = True

        # validate that the file or URL exists
        missing_err_msg = (_('"%s" does not exist.') % self.path)
        if self.a_file:
            if not os.path.isfile(self.path):
                ExceptionCollector.appendException(
                    ValidationError(message=missing_err_msg))
                return False
            else:
                self.csar = self.path
        else:  # a URL
            if not UrlUtils.validate_url(self.path):
                ExceptionCollector.appendException(
                    ValidationError(message=missing_err_msg))
                return False
            else:
                response = requests.get(self.path)
                self.csar = BytesIO(response.content)

        # validate that it is a valid zip file
        if not zipfile.is_zipfile(self.csar):
            err_msg = (_('"%s" is not a valid zip file.') % self.path)
            ExceptionCollector.appendException(
                ValidationError(message=err_msg))
            return False

        # validate that it contains the metadata file in the correct location
        self.zfile = zipfile.ZipFile(self.csar, 'r')
        filelist = self.zfile.namelist()
        if TOSCA_META in filelist:
            self.is_tosca_metadata = True
            # validate that 'Entry-Definitions' property exists in TOSCA.meta
            is_validated = self._validate_tosca_meta(filelist)
        else:
            self.is_tosca_metadata = False
            is_validated = self._validate_root_level_yaml(filelist)

        if is_validated:
            # validate that external references and imports in the main
            # template actually exist and are accessible
            main_tpl = self._read_template_yaml(self.main_template_file_name)
            self._validate_external_references(main_tpl)
        return not ExceptionCollector.exceptionsCaught()

    def get_metadata(self):
        """Return the metadata dictionary."""

        # validate the csar if not already validated
        if not self.is_validated:
            self.validate()

        # return a copy to avoid changes overwrite the original
        return dict(self.metadata) if self.metadata else None

    def _get_metadata(self, key):
        if not self.is_validated:
            self.validate()
        return self.metadata.get(key)

    def get_author(self):
        if self.is_tosca_metadata:
            return self._get_metadata('Created-By')
        else:
            # In case CSAR zip doesn't contain TOSCA.Metadata directory,
            # Created-By is defined by the template_author metadata
            return self._get_metadata('template_author')

    def get_version(self):
        if self.is_tosca_metadata:
            return self._get_metadata('CSAR-Version')
        else:
            # In case CSAR zip doesn't contain TOSCA.Metadata directory,
            # CSAR-Version is defined by the template_version metadata
            return self._get_metadata('template_version')

    def get_main_template(self):
        if not self.is_validated:
            self.validate()
        return self.main_template_file_name

    def get_main_template_yaml(self):
        main_template = self.get_main_template()
        if main_template:
            data = self.zfile.read(main_template)
            invalid_tosca_yaml_err_msg = (
                _('The file "%(template)s" in the CSAR "%(csar)s" does not '
                  'contain valid TOSCA YAML content.') %
                {'template': main_template, 'csar': self.path})
            try:
                tosca_yaml = yaml.safe_load(data)
                if type(tosca_yaml) is not dict:
                    ExceptionCollector.appendException(
                        ValidationError(message=invalid_tosca_yaml_err_msg))
                return tosca_yaml
            except Exception:
                ExceptionCollector.appendException(
                    ValidationError(message=invalid_tosca_yaml_err_msg))

    def get_description(self):
        desc = self._get_metadata('Description')
        if desc is not None:
            return desc

        self.metadata['Description'] = \
            self.get_main_template_yaml().get('description')
        return self.metadata['Description']

    def decompress(self):
        if not self.is_validated:
            self.validate()
        assert self.unzip_dir is not None
        assert self.csar
        with zipfile.ZipFile(self.csar, "r") as zf:
            zf.extractall(self.unzip_dir)

    def _validate_external_artifact_imports(self, main_tpl, tpl_filename):
        """validate the imports and artifacts"""

        self._validate_template(main_tpl, tpl_filename)

        if main_tpl:
            assert self.unzip_dir is not None
            if 'imports' in main_tpl:
                custom_service = ImportsLoader(
                    main_tpl['imports'],
                    os.path.join(self.unzip_dir, tpl_filename))

                # Get list of nested templates
                nested_tosca_tpls = custom_service.get_nested_tosca_tpls()

                # Validate external references of each nested template.
                if nested_tosca_tpls:
                    for filename, (tpl, namespace_id) in nested_tosca_tpls.items():
                        self._validate_external_artifact_imports(
                            tpl, filename)

    def _validate_external_references(self, main_tpl):
        """Extracts files referenced in the main template

        These references are currently supported:
        * imports
        * interface implementations
        * artifacts
        """
        temp_dir = None
        if self.unzip_dir is None:
            temp_dir = tempfile.TemporaryDirectory()
            self.unzip_dir = temp_dir.name
        try:
            self.decompress()
            self._validate_external_artifact_imports(
                main_tpl,
                self.main_template_file_name)
        finally:
            if temp_dir:
                self.unzip_dir = None
                temp_dir.cleanup()

    def _validate_template(self, template_data, template):
        if 'topology_template' in template_data:
            topology_template = template_data['topology_template']
            if 'node_templates' in topology_template:
                node_templates = topology_template['node_templates']

                for node_template_key in node_templates:
                    node_template = node_templates[node_template_key]
                    if 'artifacts' in node_template:
                        self._validate_artifacts(
                            node_template, node_templates, template)

                    if 'interfaces' in node_template:
                        self._validate_interfaces(
                            node_template, node_templates, template)

    def _validate_artifacts(self, node_template, node_templates, template):
        artifacts = node_template['artifacts']
        for artifact_key in artifacts:
            artifact = artifacts[artifact_key]
            if isinstance(artifact, str):
                self._validate_external_reference(
                    node_templates, template, artifact)
            elif isinstance(artifact, dict):
                if 'file' in artifact:
                    self._validate_external_reference(
                        node_templates, template, artifact['file'])
            else:
                ExceptionCollector.appendException(
                    ValueError(_('Unexpected artifact definition for "%s".')
                               % artifact_key))

    def _validate_interfaces(self, node_template, node_templates, template):
        interfaces = node_template['interfaces']
        for interface_key in interfaces:
            interface = interfaces[interface_key]
            for operation_key in interface:
                operation = interface[operation_key]
                if isinstance(operation, str):
                    self._validate_external_reference(
                        node_templates, template, operation, False)
                elif isinstance(operation, dict):
                    if 'implementation' in operation:
                        if isinstance(operation['implementation'], dict):
                            implement = operation['implementation']
                            if 'primary' in implement:
                                self._validate_external_reference(
                                    node_templates, template,
                                    implement['primary'], False)
                            elif 'dependencies' in implement:
                                self._validate_external_reference(
                                    node_templates, template,
                                    implement['dependencies'], False)
                        else:
                            self._validate_external_reference(
                                node_templates, template,
                                operation['implementation'], False)

    def _validate_external_reference(self, node_templates, tpl_file,
                                     resource_file, raise_exc=True):
        """Verify that the external resource exists

        If resource_file is a URL verify that the URL is valid.
        If resource_file is a relative path verify that the path is valid
        considering base folder (self.temp_dir) and tpl_file.
        If resource_file is not a path verify that it is a valid
        implementation name by matching the artifact name.
        Note that in a CSAR resource_file cannot be an absolute path.
        """
        if UrlUtils.validate_url(resource_file):
            msg = (_('The resource at "%s" cannot be accessed.') %
                   resource_file)
            try:
                if UrlUtils.url_accessible(resource_file):
                    return
                else:
                    ExceptionCollector.appendException(
                        URLException(what=msg))
            except Exception:
                ExceptionCollector.appendException(
                    URLException(what=msg))

        assert self.unzip_dir is not None
        if os.path.isfile(os.path.join(self.unzip_dir,
                                       os.path.dirname(tpl_file),
                                       resource_file)):
            return
        elif self._validate_artifact_name(node_templates):
            return
        else:
            raise_exc = True

        if raise_exc:
            ExceptionCollector.appendException(
                ValueError(_('The resource "%s" does not exist.')
                           % resource_file))

    def _read_template_yaml(self, template):
        data = self.zfile.read(template)
        invalid_tosca_yaml_err_msg = (
            _('The file "%(template)s" in the CSAR "%(csar)s" does not '
              'contain valid YAML content.') %
            {'template': template, 'csar': self.path})
        try:
            tosca_yaml = yaml.safe_load(data)
            if type(tosca_yaml) is not dict:
                ExceptionCollector.appendException(
                    ValidationError(message=invalid_tosca_yaml_err_msg))
                return None
            return tosca_yaml
        except Exception:
            ExceptionCollector.appendException(
                ValidationError(message=invalid_tosca_yaml_err_msg))
            return None

    def _validate_tosca_meta(self, filelist):
        tosca = self._read_template_yaml(TOSCA_META)
        if tosca is None:
            return False

        self.metadata = tosca

        if 'Entry-Definitions' not in self.metadata:
            err_msg = (_('The CSAR "%s" is missing the required metadata '
                         '"Entry-Definitions" in '
                         '"TOSCA-Metadata/TOSCA.meta".')
                       % self.path)
            ExceptionCollector.appendException(
                ValidationError(message=err_msg))
            return False

        # validate that 'Entry-Definitions' metadata value points to an
        # existing file in the CSAR
        entry = self.metadata.get('Entry-Definitions')
        if entry and entry not in filelist:
            err_msg = (_('The "Entry-Definitions" file defined in the '
                         'CSAR "%s" does not exist.') % self.path)
            ExceptionCollector.appendException(
                ValidationError(message=err_msg))
            return False

        self.main_template_file_name = entry
        return True

    def _validate_root_level_yaml(self, filelist):
        root_files = []
        for file in filelist:
            if '/' not in file:
                __, file_extension = os.path.splitext(file)
                if file_extension in ['.yaml', '.yml']:
                    root_files.append(file)

        if not len(root_files) == 1:
            err_msg = (_('CSAR file should contain only one root level yaml'
                         ' file. Found "%d" yaml file(s).') % len(root_files))
            ExceptionCollector.appendException(
                ValidationError(message=err_msg))
            return False

        template_data = self._read_template_yaml(root_files[0])
        if template_data is None:
            return False

        tosca_version = template_data.get('tosca_definitions_version')
        if tosca_version == 'tosca_simple_yaml_1_0':
            err_msg = (_('"%s" is not a valid CSAR as it does not contain'
                         ' the required file "TOSCA.meta" in the'
                         ' folder "TOSCA-Metadata".') % self.path)
            ExceptionCollector.appendException(
                ValidationError(message=err_msg))
            return False

        self.metadata = template_data.get('metadata')
        self.main_template_file_name = root_files[0]
        return True

    def _validate_artifact_name(self, node_templates):
        artifact_name = []
        for node_template_key in node_templates:
            node_template = node_templates[node_template_key]
            if 'artifacts' in node_template:
                artifacts = node_template['artifacts']
                for artifact_key in artifacts:
                    artifact_name.append(artifact_key)

            if 'interfaces' in node_template:
                interfaces = node_template['interfaces']
                for interface_key in interfaces:
                    interface = interfaces[interface_key]
                    for operation_key in interface:
                        operation = interface[operation_key]
                        if isinstance(operation, str):
                            if operation in artifact_name:
                                return True
                        elif isinstance(operation, dict):
                            if 'implementation' in operation:
                                if isinstance(operation['implementation'],
                                              dict):
                                    implement = operation['implementation']
                                    if 'primary' in implement:
                                        if (implement['primary'] in
                                                artifact_name):
                                            return True
                                    elif 'dependencies' in implement:
                                        if (implement['dependencies'] in
                                                artifact_name):
                                            return True
                                else:
                                    if (operation['implementation'] in
                                            artifact_name):
                                        return True
        return False
