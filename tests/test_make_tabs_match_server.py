"""The Make page and the server must agree: every /api/quick tab posts exactly the file fields the tool reads."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import server

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

LOAD = """
global.window = {}; global.localStorage = {getItem() { return null; }, setItem() {}};
global.document = {getElementById() { return null; }, addEventListener() {}};
(0, eval)(require('fs').readFileSync(process.argv[1], 'utf8'));
process.stdout.write(JSON.stringify(window.SkellyMake.TABS));
"""


def tabs():
    done = subprocess.run(["node", "-e", LOAD, str(ROOT / "static" / "make.js")], capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def test_every_quick_tool_has_one_tab_and_the_file_fields_match():
    by_id = {t["id"]: t for t in tabs()}
    assert len(by_id) == len(tabs()), "tab ids are unique"
    for tool_id, tool in server.QUICK_TOOLS.items():
        tab = by_id.get(tool_id)
        assert tab is not None, f"{tool_id} has no tab on the Make page"
        assert tab["endpoint"] == f"/api/quick/{tool_id}"
        files = {f["name"]: f for f in tab["fields"] if f["type"] == "file"}
        wanted = {name: required for name, _, required in tool.inputs}
        assert set(files) == set(wanted), f"{tool_id}: the page sends {sorted(files)}, the server reads {sorted(wanted)}"
        for name, kind, required in tool.inputs:
            assert bool(files[name].get("required")) == required, f"{tool_id}.{name} required flag"
            assert bool(files[name].get("multiple")) == kind.endswith("s"), f"{tool_id}.{name} multiple flag"


def test_every_tab_has_a_blurb_a_button_and_a_label_on_every_field():
    for tab in tabs():
        assert len(tab["blurb"]) > 20 and tab["go"] and tab["title"], tab["id"]
        names = [f["name"] for f in tab["fields"]]
        assert len(names) == len(set(names)), f"{tab['id']} repeats a field name"
        for f in tab["fields"]:
            assert f.get("label"), (tab["id"], f["name"])
            if f["type"] == "select":
                assert any(v == f["value"] for v, _ in f["options"]), f"{tab['id']}.{f['name']} default is not an option"
