"""Task 8: CLI entry point (build_parser + main + COMMAND_DISPATCH) 单元测试

Covers:
- build_parser() returns a valid parser with all 9 subcommands
- Each subcommand has correct arguments and help text
- COMMAND_DISPATCH contains all 9 command-to-handler mappings
- main() dispatches correctly for valid/invalid/no commands
- No orphan subparser registrations at module level
"""

import sys, os, tempfile, shutil, unittest, argparse
from argparse import ArgumentParser
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as mem


class TestBuildParser(unittest.TestCase):
    """build_parser() must return a complete ArgumentParser with all subcommands."""

    EXPECTED_COMMANDS = [
        "config", "review",        "add", "search", "list", "delete", "update",
        "evolve", "load", "export", "status", "vec", "migrate",
    ]

    def test_returns_parser(self):
        """build_parser() returns an ArgumentParser (not None)."""
        parser = mem.build_parser()
        self.assertIsInstance(parser, ArgumentParser)

    def test_has_all_subcommands(self):
        """Parser registers all 9 subcommands."""
        parser = mem.build_parser()
        # Access subparsers via _actions
        sub_actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        self.assertEqual(len(sub_actions), 1,
                         "Should have exactly one subparsers action")
        choices = sub_actions[0].choices
        self.assertCountEqual(list(choices.keys()), self.EXPECTED_COMMANDS)

    def test_add_subcommand_args(self):
        """add subparser has correct arguments."""
        parser = mem.build_parser()
        add_parser = parser._actions[-1].choices["add"]
        add_args = {a.dest for a in add_parser._actions}
        self.assertIn("type", add_args)
        self.assertIn("content", add_args)
        self.assertIn("topics", add_args)
        self.assertIn("no_evolve", add_args)
        # type should have choices
        type_action = [a for a in add_parser._actions if a.dest == "type"][0]
        self.assertIsNotNone(type_action.choices)

    def test_load_subcommand_limit(self):
        """load subparser has --limit argument."""
        parser = mem.build_parser()
        load_parser = parser._actions[-1].choices["load"]
        load_args = {a.dest for a in load_parser._actions}
        self.assertIn("limit", load_args)

    def test_export_subcommand_dir(self):
        """export subparser has --dir argument."""
        parser = mem.build_parser()
        exp_parser = parser._actions[-1].choices["export"]
        exp_args = {a.dest for a in exp_parser._actions}
        self.assertIn("dir", exp_args)

    def test_vec_subcommand_cmd(self):
        """vec subparser has vec_cmd positional with choices."""
        parser = mem.build_parser()
        vec_parser = parser._actions[-1].choices["vec"]
        vec_args = {a.dest for a in vec_parser._actions}
        self.assertIn("vec_cmd", vec_args)
        cmd_action = [a for a in vec_parser._actions if a.dest == "vec_cmd"][0]
        self.assertCountEqual(cmd_action.choices, ["enable", "rebuild", "status"])

    def test_evolve_parses(self):
        """evolve subparser can be parsed."""
        p = mem.build_parser()
        args = p.parse_args(["evolve"])
        self.assertEqual(args.command, "evolve")

    def test_parser_parse_add(self):
        """Parser can parse 'add --type workflow --content test'."""
        p = mem.build_parser()
        args = p.parse_args(["add", "--type", "workflow", "--content", "hello"])
        self.assertEqual(args.command, "add")
        self.assertEqual(args.type, "workflow")
        self.assertEqual(args.content, "hello")

    def test_parser_parse_search(self):
        """Parser can parse 'search keyword --limit 3'."""
        p = mem.build_parser()
        args = p.parse_args(["search", "memory", "--limit", "3"])
        self.assertEqual(args.command, "search")
        self.assertEqual(args.keywords, "memory")
        self.assertEqual(args.limit, 3)

    def test_parser_parse_evolve(self):
        """Parser can parse 'evolve'."""
        p = mem.build_parser()
        args = p.parse_args(["evolve"])
        self.assertEqual(args.command, "evolve")

    def test_parser_parse_status(self):
        """Parser can parse 'status'."""
        p = mem.build_parser()
        args = p.parse_args(["status"])
        self.assertEqual(args.command, "status")

    def test_parser_parse_vec(self):
        """Parser can parse 'vec rebuild'."""
        p = mem.build_parser()
        args = p.parse_args(["vec", "rebuild"])
        self.assertEqual(args.command, "vec")
        self.assertEqual(args.vec_cmd, "rebuild")

    def test_parser_parse_vec_default(self):
        """Parser parses 'vec' with default vec_cmd='status'."""
        p = mem.build_parser()
        args = p.parse_args(["vec"])
        self.assertEqual(args.command, "vec")
        self.assertEqual(args.vec_cmd, "status")

    def test_parser_parse_migrate(self):
        """Parser can parse 'migrate'."""
        p = mem.build_parser()
        args = p.parse_args(["migrate"])
        self.assertEqual(args.command, "migrate")

    def test_parser_parse_delete(self):
        """Parser can parse 'delete 42'."""
        p = mem.build_parser()
        args = p.parse_args(["delete", "42"])
        self.assertEqual(args.command, "delete")
        self.assertEqual(args.seq, 42)

    def test_parser_parse_update(self):
        """Parser can parse 'update 5 --content new'."""
        p = mem.build_parser()
        args = p.parse_args(["update", "5", "--content", "new"])
        self.assertEqual(args.command, "update")
        self.assertEqual(args.seq, 5)
        self.assertEqual(args.content, "new")




class TestCommandDispatch(unittest.TestCase):
    """COMMAND_DISPATCH must map all 9 commands to correct handler functions."""

    def test_all_commands_mapped(self):
        """COMMAND_DISPATCH has all 13 entries."""
        expected = {"config", "review",
        "add", "search", "list", "delete", "update",
                    "evolve", "load", "export", "status", "vec", "migrate"}
        self.assertCountEqual(mem.COMMAND_DISPATCH.keys(), expected)

    def test_add_maps_to_cmd_add(self):
        self.assertIs(mem.COMMAND_DISPATCH["add"], mem.cmd_add)

    def test_search_maps_to_cmd_search(self):
        self.assertIs(mem.COMMAND_DISPATCH["search"], mem.cmd_search)

    def test_list_maps_to_cmd_list(self):
        self.assertIs(mem.COMMAND_DISPATCH["list"], mem.cmd_list)

    def test_evolve_maps_to_cmd_evolve(self):
        self.assertIs(mem.COMMAND_DISPATCH["evolve"], mem.cmd_evolve)

    def test_load_maps_to_cmd_load(self):
        self.assertIs(mem.COMMAND_DISPATCH["load"], mem.cmd_load)

    def test_export_maps_to_cmd_export(self):
        self.assertIs(mem.COMMAND_DISPATCH["export"], mem.cmd_export)

    def test_status_maps_to_cmd_status(self):
        self.assertIs(mem.COMMAND_DISPATCH["status"], mem.cmd_status)

    def test_vec_maps_to_cmd_vec(self):
        self.assertIs(mem.COMMAND_DISPATCH["vec"], mem.cmd_vec)

    def test_migrate_maps_to_cmd_migrate(self):
        self.assertIs(mem.COMMAND_DISPATCH["migrate"], mem.cmd_migrate)


    def test_delete_maps_to_cmd_delete(self):
        self.assertIs(mem.COMMAND_DISPATCH["delete"], mem.cmd_delete)

    def test_update_maps_to_cmd_update(self):
        self.assertIs(mem.COMMAND_DISPATCH["update"], mem.cmd_update)

class TestMainEntry(unittest.TestCase):
    """main() entry point dispatch logic."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="cli_test_")
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.LOCK_PATH = os.path.join(self.test_dir, ".lock")

    def tearDown(self):
        try:
            mem.init_db().close()
        except Exception:
            pass
        shutil.rmtree(self.test_dir, ignore_errors=True)
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)

    def _capture_main(self, argv):
        """Run main() with given argv, return (exit_code, stdout)."""
        old_argv, old_stdout = sys.argv, sys.stdout
        sys.argv = ["main.py"] + argv
        sys.stdout = StringIO()
        exit_code = None
        try:
            mem.main()
        except SystemExit as e:
            exit_code = e.code
        finally:
            output = sys.stdout.getvalue()
            sys.argv, sys.stdout = old_argv, old_stdout
        return exit_code, output

    def test_main_dispatch_add(self):
        """main() dispatches 'add' command successfully."""
        # init_db to create dir
        mem.init_db()
        rc, out = self._capture_main([
            "add", "--type", "workflow", "--content", "test entry", "--no-evolve",
        ])
        self.assertEqual(rc, 0)
        self.assertIn("已记录", out)

    def test_main_unknown_command(self):
        """main() exits with code 2 for unknown command (argparse intercepts)."""
        rc, out = self._capture_main(["unknown_cmd"])
        # argparse intercepts invalid choice before main() handler
        # Error goes to stderr, not stdout
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")

    def test_main_no_command(self):
        """main() shows help when no command given."""
        rc, out = self._capture_main([])
        # main() handles missing command with sys.exit(1)
        self.assertEqual(rc, 1)
        self.assertIn("usage", out)

    def test_main_invalid_type(self):
        """main() rejects invalid --type value."""
        mem.init_db()
        rc, out = self._capture_main([
            "add", "--type", "invalid_type", "--content", "x",
        ])
        # argparse intercepts invalid --type choice → exit 2
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")


class TestNoOrphanCode(unittest.TestCase):
    """The module must not have orphan subparser registrations after
    the `if __name__ == "__main__"` block."""

    def test_no_module_level_subparsers(self):
        """No sub.add_parser() calls at module level outside
        if __name__ and build_parser()."""
        import inspect, re

        # Find all top-level (module-level) sub.add_parser calls
        src = inspect.getsource(mem)
        # Find lines with sub.add_parser that are NOT inside build_parser
        # and NOT inside if __name__
        lines = src.split("\n")
        in_build_parser = False
        in_if_name_main = False
        problems = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if "def build_parser" in stripped:
                in_build_parser = True
            elif 'if __name__ == "__main__"' in stripped:
                in_if_name_main = True
            elif stripped == "def main():":
                in_build_parser = False
            elif stripped == "def " in stripped and stripped.startswith("def "):
                # Other function definitions
                pass

            if "sub.add_parser" in stripped:
                if not in_build_parser and not in_if_name_main:
                    problems.append((i + 1, stripped))

        self.assertEqual(
            len(problems), 0,
            f"Found orphan sub.add_parser calls at module level: {problems}"
        )

    @classmethod
    def tearDownClass(cls):
        # Clean up any DB files created during tests
        for d in ["/tmp"] if False else []:
            pass


if __name__ == "__main__":
    unittest.main()
