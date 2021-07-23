import enum
import os
import shutil
import sys

import click
from shed import shed

# from terminusdb_client.woqlschema.woql_schema import TerminusClass
import terminusdb_client.woqlschema.woql_schema as woqlschema
from terminusdb_client.errors import DatabaseError, InterfaceError
from terminusdb_client.woql_type import from_woql_type
from terminusdb_client.woqlclient.woqlClient import WOQLClient


@click.group()
def terminusdb():
    pass


@click.command()
def startproject():
    """Copy the template files into current working directory"""
    this_file_dir = os.path.dirname(os.path.abspath(__file__))
    files = os.listdir(this_file_dir)
    for file in files:
        names = file.split("_")
        if names[-1] == "template.py":
            shutil.copyfile(
                this_file_dir + "/" + file, os.getcwd() + "/" + names[0] + ".py"
            )


def _load_settings():
    sys.path.append(os.getcwd())

    try:
        _temp = __import__("settings", globals(), locals(), ["SERVER", "DATABASE"], 0)
        SERVER = _temp.SERVER
        DATABASE = _temp.DATABASE
        return {"SERVER": SERVER, "DATABASE": DATABASE}
    except ImportError:
        msg = "Cannot find settings.py"
        raise ImportError(msg)


def _connect(settings):
    # SETTINGS = _load_settings()
    SERVER = settings["SERVER"]
    DATABASE = settings["DATABASE"]

    client = WOQLClient(SERVER)
    client.connect()
    try:
        client.create_database(DATABASE)
        return client, f"{DATABASE} created."
    except DatabaseError as error:
        if "Database already exists." in error.message:
            client.connect(db=DATABASE)
            return client, f"Connected to {DATABASE}."
        else:
            raise InterfaceError(f"Cannot connect to {DATABASE}.")


def _create_script(obj_list):
    class ResultObj:
        def __init__(self, name, parent, script=None):
            self.name = name
            if parent in dir(woqlschema):
                self.parent = None
            else:
                self.parent = parent
            if script is None:
                if type(parent) == str or len(parent) == 1:
                    self.script = f"class {name}({parent}):\n"
                elif len(parent) > 1:
                    self.script = f"class {name}({', '.join(parent)}):\n"
                else:
                    self.script = f"class {name}:\n"
            else:
                self.script = script

        def add_key(self, key: str, fields: list = None):
            if fields is None:
                self.script += f"    _key = {key}Key()\n"
            else:
                self.script += f"    _key = {key}Key({fields})\n"

        def add_subdoc(self):
            self.script += "    _subdocument = []\n"

        def add_abstract(self):
            self.script += "    _abstract = []\n"

        def add_docstring(self, obj_dict):
            self.script += '    """'
            if obj_dict["@documentation"].get("@comment"):
                self.script += f'{obj_dict["@documentation"]["@comment"]}'
            if obj_dict["@documentation"].get("@properties"):
                self.script += "\n\n    Attributes\n    ----------\n"
                for prop, discription in obj_dict["@documentation"][
                    "@properties"
                ].items():
                    self.script += f"    {prop} : {from_woql_type(obj_dict[prop], skip_convert_error=True, as_str=True)}\n        {discription}\n"
                self.script += "    "
            self.script += '"""\n'

    import_objs = []
    print_script = """####
# This is the script for storing the schema of your TerminusDB
# database for your project.
# Use 'terminusdb commit' to commit changes to the database and
# use 'terminusdb sync' to change this file according to
# the exsisting database schema
####\n\n"""
    for obj_str in dir(woqlschema):
        obj = eval(f"woqlschema.{obj_str}")
        if (
            isinstance(obj, woqlschema.TerminusClass)
            or isinstance(obj, enum.EnumMeta)
            or isinstance(obj, woqlschema.TerminusKey)
        ):
            import_objs.append(obj_str)
    print_script += "from typing import List, Optional, Set\n"
    print_script += (
        f"from terminusdb_client.woqlschema import {', '.join(import_objs)}\n"
    )
    # print("from typing import List, Optional, Set\n")
    # print(f"from terminusdb_client.woqlschema import {', '.join(import_objs)}\n")

    result_list = []
    for obj in obj_list:
        # print(obj)
        if obj.get("@id"):
            if obj.get("@inherits"):
                result_obj = ResultObj(obj["@id"], obj["@inherits"])
            elif obj["@type"] == "Class":
                result_obj = ResultObj(obj["@id"], "DocumentTemplate")
            elif obj["@type"] == "Enum":
                result_obj = ResultObj(obj["@id"], "EnumTemplate")
                for value in obj["@value"]:
                    if " " not in value:
                        result_obj.script += f"    {value} = ()\n"
                    else:
                        result_obj.script += (
                            f"    {value.replace(' ','_')} = '{value}'\n"
                        )
            if obj.get("@documentation"):
                result_obj.add_docstring(obj)
            if obj.get("@subdocument") is not None:
                result_obj.add_subdoc()
            elif obj.get("@key"):
                result_obj.add_key(obj["@key"]["@type"], obj["@key"].get("@fields"))

            if obj.get("@abstract") is not None:
                result_obj.add_abstract()
            result_list.append(result_obj)

            for key, value in obj.items():
                if key[0] != "@":
                    result_obj.script += f"    {key}:{from_woql_type(value, skip_convert_error=True, as_str=True)}\n"

    # sorts depends on the object inherits order
    printed = []
    while len(result_list) > 0:
        obj = result_list.pop(0)
        if obj.parent is None:
            # print(obj.script)
            print_script += obj.script
            printed.append(obj.name)
        elif type(obj.parent) == str and obj.parent in printed:
            # print(obj.script)
            print_script += obj.script
            printed.append(obj.name)
        else:
            parent_is_in = False
            for mama in obj.parent:
                if mama in printed:
                    parent_is_in = True
            if parent_is_in:
                # print(obj.script)
                print_script += obj.script
                printed.append(obj.name)
            else:
                result_list.append(obj)
    return print_script


@click.command()
def sync():
    settings = _load_settings()
    DATABASE = settings["DATABASE"]
    client, msg = _connect(settings)
    print(msg)
    all_existing_obj = client.get_all_documents(graph_type="schema")
    all_obj_list = []
    for obj in all_existing_obj:
        all_obj_list.append(obj)
    if len(all_obj_list) > 1:
        print_script = _create_script(all_obj_list)
        # print(print_script)
        file = open("schema.py", "w")
        file.write(shed(source_code=print_script))
        file.close()
        print(f"schema.py is updated with {DATABASE} schema.")
    else:
        print(f"{DATABASE} schema is empty so schema.py has not be changed.")


@click.command()
def commit():
    settings = _load_settings()
    DATABASE = settings["DATABASE"]
    client, msg = _connect(settings)
    print(msg)
    schema_plan = __import__("schema", globals(), locals(), [], 0)
    all_existing_obj = client.get_all_documents(graph_type="schema")
    all_existing_id = list(map(lambda x: x.get("@id"), all_existing_obj))
    insert_schema = woqlschema.WOQLSchema()
    update_schema = woqlschema.WOQLSchema()
    for obj_str in dir(schema_plan):
        obj = eval(f"schema_plan.{obj_str}")
        if isinstance(obj, woqlschema.TerminusClass) or isinstance(obj, enum.EnumMeta):
            if obj_str not in dir(woqlschema):
                if obj_str in all_existing_id:
                    obj._schema = update_schema
                    update_schema.add_obj(obj)
                else:
                    obj._schema = insert_schema
                    insert_schema.add_obj(obj)
    # print("Update")
    # print(update_schema.to_dict())
    # print("Insert")
    # print(insert_schema.to_dict())
    client.replace_document(
        update_schema,
        commit_msg="Schema updated by Python client.",
        graph_type="schema",
    )
    client.insert_document(
        insert_schema,
        commit_msg="Schema object insert by Python client.",
        graph_type="schema",
    )
    print(f"{DATABASE} schema updated.")


@click.command()
@click.argument("database")
def deletedb(database):
    SETTINGS = _load_settings()
    SERVER = SETTINGS["SERVER"]
    DATABASE = SETTINGS["DATABASE"]
    if database != DATABASE:
        raise ValueError(
            "Name provided does not match project database name. You can only delete the database in this project."
        )
    else:
        client = WOQLClient(SERVER)
        client.connect()
        client.delete_database(database, client._account)
        print(f"{database} deleted.")


terminusdb.add_command(startproject)
terminusdb.add_command(sync)
terminusdb.add_command(commit)
terminusdb.add_command(deletedb)