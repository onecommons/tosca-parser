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

from toscaparser.properties import Property


class Capability(object):
    '''TOSCA built-in capabilities type.'''

    def __init__(self, name, properties, definition, custom_def=None):
        self.name = name
        self._properties = properties
        self._properties_objects = None
        self.type_definition = definition
        self.custom_def = custom_def
        self.type = definition.type

    def get_properties_objects(self):
        '''Return a list of property objects.'''
        if self._properties_objects is None:
            properties = []
            props = self._properties
            if props:
                for name, value in props.items():
                    props_def = self.type_definition.get_properties_def()
                    if props_def and name in props_def:
                        properties.append(Property(name, value,
                                                  props_def[name].schema,
                                                  self.custom_def))
            self._properties_objects = properties
        return self._properties_objects

    def get_properties(self):
        '''Return a dictionary of property name-object pairs.'''
        return {prop.name: prop
                for prop in self.get_properties_objects()}

    def get_property_value(self, name):
        '''Return the value of a given property name.'''
        props = self.get_properties()
        if props and name in props:
            return props[name].value

    def builtin_properties(self):
        return {}

    def update_property(self, name, value):
        props = self.get_properties()
        if name in props:
            props[name].value = value
        elif self.type_definition:
            prop_def = self.type_definition.get_properties_def().get(name)
            if prop_def:
                prop = Property(
                    prop_def.name,
                    value,
                    prop_def.schema,
                    self.custom_def,
                )
                self._properties_objects.append(prop)

    def is_derived_from(self, type_str):
        '''Check if object inherits from the given type.

        Returns true if this object is derived from 'type_str'.
        False otherwise.
        '''
        if not self.type:
            return False
        elif self.type == type_str:
            return True
        return self.type_definition.is_derived_from(type_str)
