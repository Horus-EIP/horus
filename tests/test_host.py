# SPDX-License-Identifier: Apache-2.0
import json
import sys

import pytest

from horus_bench_kit import host
from horus_bench_kit.host import (
    disk_label,
    docker_data_path,
    machine_section,
    missing_fields,
    parse_cpuinfo,
    parse_diskutil,
    parse_dmidecode_memory,
    parse_docker_info,
    parse_lsblk_disk,
    parse_macos_memory,
    parse_meminfo_total,
    parse_windows_cpu,
    parse_windows_disk,
    parse_windows_memory,
    ram_label,
)
from horus_bench_kit.shell import COMMAND_NOT_STARTED, Shell

GIB = 2**30

CPUINFO = """processor\t: 0
vendor_id\t: GenuineExample
model name\t: Example CPU 6C @ 3.0GHz
physical id\t: 0
core id\t\t: 0
flags\t\t: fpu sse sse2 avx avx2 fma

processor\t: 1
model name\t: Example CPU 6C @ 3.0GHz
physical id\t: 0
core id\t\t: 0
flags\t\t: fpu sse sse2 avx avx2 fma

processor\t: 2
model name\t: Example CPU 6C @ 3.0GHz
physical id\t: 0
core id\t\t: 1
flags\t\t: fpu sse sse2 avx avx2 fma
"""

DMIDECODE = """# dmidecode 3.5
Handle 0x0010, DMI type 17, 92 bytes
Memory Device
\tSize: 8 GB
\tType: DDR4
\tSpeed: 3200 MT/s
\tConfigured Memory Speed: 2933 MT/s

Handle 0x0011, DMI type 17, 92 bytes
Memory Device
\tSize: No Module Installed
\tType: Unknown
\tSpeed: Unknown

Handle 0x0012, DMI type 17, 92 bytes
Memory Device
\tSize: 8192 MB
\tType: DDR4
\tSpeed: 3200 MT/s
\tConfigured Memory Speed: 2933 MT/s
"""

WINDOWS_MEMORY = json.dumps(
    [
        {"Capacity": 8 * GIB, "Speed": 3200, "ConfiguredClockSpeed": 3200, "SMBIOSMemoryType": 26},
        {"Capacity": 8 * GIB, "Speed": 3200, "ConfiguredClockSpeed": 3200, "SMBIOSMemoryType": 26},
    ]
)

LSBLK_NVME = json.dumps(
    {
        "blockdevices": [
            {
                "name": "nvme0n1p2",
                "type": "part",
                "rota": False,
                "tran": None,
                "model": None,
                "children": [
                    {"name": "nvme0n1", "type": "disk", "rota": False, "tran": "nvme", "model": "Example NVMe 1TB"}
                ],
            }
        ]
    }
)

LSBLK_LVM_ON_SATA_HDD = json.dumps(
    {
        "blockdevices": [
            {
                "name": "vg-root",
                "type": "lvm",
                "rota": "1",
                "children": [
                    {
                        "name": "sda3",
                        "type": "part",
                        "rota": "1",
                        "children": [{"name": "sda", "type": "disk", "rota": "1", "tran": "sata", "model": "Example HDD 2TB  "}],
                    }
                ],
            }
        ]
    }
)

DOCKER_INFO = json.dumps(
    {
        "MemTotal": 8_221_196_288,
        "NCPU": 12,
        "OperatingSystem": "Docker Desktop",
        "KernelVersion": "6.10.14-linuxkit",
        "ServerVersion": "27.3.1",
        "CgroupVersion": "2",
        "DockerRootDir": "/var/lib/docker",
    }
)


class TestLinux:
    def test_cpuinfo_gives_model_physical_cores_and_avx2(self):
        assert parse_cpuinfo(CPUINFO) == {
            "cpu_model": "Example CPU 6C @ 3.0GHz",
            "physical_cores": 2,
            "avx2": True,
        }

    def test_cpu_without_avx2_flag(self):
        facts = parse_cpuinfo("model name : Old CPU\nflags : fpu sse sse2 avx\n")
        assert facts["avx2"] is False
        assert facts["physical_cores"] is None

    def test_unreadable_cpuinfo_leaves_everything_unknown(self):
        assert parse_cpuinfo(None) == {"cpu_model": None, "physical_cores": None, "avx2": None}

    def test_meminfo_total(self):
        assert parse_meminfo_total("MemTotal:       16303916 kB\nMemFree: 1 kB\n") == 16303916 * 1024
        assert parse_meminfo_total("") is None

    def test_dmidecode_gives_installed_size_type_and_configured_speed(self):
        assert parse_dmidecode_memory(DMIDECODE) == {
            "ram_installed_bytes": 16 * GIB,
            "ram_speed": "2933 MT/s",
            "ram_type": "DDR4",
            "ram_modules": 2,
        }

    def test_dmidecode_without_root_gives_nothing(self):
        assert parse_dmidecode_memory(None) == {
            "ram_installed_bytes": None,
            "ram_speed": None,
            "ram_type": None,
            "ram_modules": None,
        }

    def test_lsblk_nvme_partition_resolves_to_its_disk(self):
        assert parse_lsblk_disk(LSBLK_NVME) == {"disk_type": "NVMe SSD", "disk_model": "Example NVMe 1TB"}

    def test_lsblk_lvm_on_a_sata_hard_disk(self):
        assert parse_lsblk_disk(LSBLK_LVM_ON_SATA_HDD) == {"disk_type": "SATA HDD", "disk_model": "Example HDD 2TB"}

    def test_lsblk_garbage_gives_nothing(self):
        assert parse_lsblk_disk("not json") == {}
        assert parse_lsblk_disk(json.dumps({"blockdevices": [{"name": "loop0", "type": "loop"}]})) == {}


class TestWindows:
    def test_processor_name_and_core_count(self):
        text = json.dumps({"Name": "Example CPU 4C @ 2.40GHz  ", "NumberOfCores": 4, "NumberOfLogicalProcessors": 8})
        assert parse_windows_cpu(text) == {"cpu_model": "Example CPU 4C @ 2.40GHz", "physical_cores": 4}

    def test_memory_modules_give_size_type_and_speed(self):
        assert parse_windows_memory(WINDOWS_MEMORY) == {
            "ram_installed_bytes": 16 * GIB,
            "ram_speed": "3200 MT/s",
            "ram_type": "DDR4",
            "ram_modules": 2,
        }

    def test_single_module_comes_back_as_an_object(self):
        text = json.dumps({"Capacity": 8 * GIB, "Speed": 6400, "ConfiguredClockSpeed": 6400, "SMBIOSMemoryType": 35})
        facts = parse_windows_memory(text)
        assert facts["ram_type"] == "LPDDR5"
        assert facts["ram_speed"] == "6400 MT/s"

    def test_physical_disk(self):
        text = json.dumps({"FriendlyName": "Example NVMe 2TB", "MediaType": "SSD", "BusType": "NVMe"})
        assert parse_windows_disk(text) == {"disk_type": "NVMe SSD", "disk_model": "Example NVMe 2TB"}
        assert parse_windows_disk("") == {}


class TestMacos:
    def test_memory_type_and_speed(self):
        text = "Memory:\n\n    Memory Slots:\n\n      Size: 8 GB\n      Type: DDR4\n      Speed: 2667 MHz\n"
        assert parse_macos_memory(text) == {"ram_speed": "2667 MT/s", "ram_type": "DDR4"}

    def test_apple_silicon_disk(self):
        text = "   Device / Media Name:       EXAMPLE SSD 512\n   Protocol:                  Apple Fabric\n   Solid State:               Yes\n"
        assert parse_diskutil(text) == {"disk_type": "NVMe SSD", "disk_model": "EXAMPLE SSD 512"}


class TestDiskLabel:
    def test_labels(self):
        assert disk_label(transport="nvme") == "NVMe SSD"
        assert disk_label(transport="sata", rotational=False) == "SATA SSD"
        assert disk_label(rotational=True) == "HDD"
        assert disk_label(media="SSD", transport="USB") == "USB SSD"
        assert disk_label(media="Unspecified") is None


class TestDocker:
    def test_docker_info_gives_the_memory_docker_can_use(self):
        assert parse_docker_info(DOCKER_INFO) == {
            "mem_total_bytes": 8_221_196_288,
            "cpus": 12,
            "operating_system": "Docker Desktop",
            "kernel": "6.10.14-linuxkit",
            "server_version": "27.3.1",
            "cgroup_version": "2",
            "root_dir": "/var/lib/docker",
        }

    def test_daemon_down_gives_no_docker_facts(self):
        assert parse_docker_info(json.dumps({"ServerErrors": ["Cannot connect"]})) is None
        assert parse_docker_info(None) is None

    def test_docker_data_path_is_the_docker_root_on_linux(self, monkeypatch, tmp_path):
        monkeypatch.setattr(host.sys, "platform", "linux")
        assert str(docker_data_path({"root_dir": "/var/lib/docker"})).replace("\\", "/") == "/var/lib/docker"
        monkeypatch.setattr(host.sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        assert docker_data_path({"root_dir": "/var/lib/docker"}) == tmp_path


class TestMachineSection:
    collected = {
        "cpu_model": ("Example CPU 6C", "/proc/cpuinfo"),
        "physical_cores": (6, "/proc/cpuinfo"),
        "avx2": (True, "/proc/cpuinfo"),
        "ram_total_bytes": (int(15.4 * GIB), "/proc/meminfo"),
        "ram_installed_bytes": (16 * GIB, "dmidecode"),
        "ram_speed": (None, "dmidecode"),
        "disk_type": ("NVMe SSD", "lsblk (/dev/nvme0n1p2)"),
    }

    def test_values_sources_and_ram_label(self):
        machine = machine_section("bench-01", self.collected, {}, parse_docker_info(DOCKER_INFO))
        assert list(machine) == [
            "reference",
            "cpu_model",
            "physical_cores",
            "logical_cpus",
            "avx2",
            "ram",
            "ram_total_bytes",
            "ram_installed_bytes",
            "ram_modules",
            "ram_type",
            "ram_speed",
            "disk_type",
            "disk_model",
            "os",
            "docker",
            "sources",
        ]
        assert machine["reference"] == "bench-01"
        assert machine["cpu_model"] == "Example CPU 6C"
        assert machine["ram"] == "16 GiB installed, 15.4 GiB usable"
        assert machine["ram_speed"] is None
        assert machine["disk_type"] == "NVMe SSD"
        assert machine["docker"]["mem_total_bytes"] == 8_221_196_288
        assert machine["sources"]["disk_type"] == "lsblk (/dev/nvme0n1p2)"
        assert "ram_speed" not in machine["sources"]
        json.dumps(machine)

    def test_given_values_win_and_are_marked(self):
        overrides = {"ram_speed": "3200 MT/s", "disk_type": "SATA SSD", "cpu_model": None}
        machine = machine_section("bench-01", self.collected, overrides, None)
        assert machine["ram_speed"] == "3200 MT/s"
        assert machine["disk_type"] == "SATA SSD"
        assert machine["sources"]["ram_speed"] == "given"
        assert machine["cpu_model"] == "Example CPU 6C"

    def test_missing_fields_say_which_option_to_pass(self):
        machine = machine_section("bench-01", self.collected, {}, None)
        missing = missing_fields(machine)
        assert len(missing) == 1
        assert missing[0].startswith("ram_speed: pass --ram-speed")

    def test_ram_label_without_installed_size(self):
        assert ram_label(int(7.6 * GIB), None) == "7.6 GiB usable"
        assert ram_label(None, None) is None


class TestCollectHost:
    def test_windows_collection_uses_cim_queries(self, monkeypatch):
        replies = {
            host.WINDOWS_CPU_QUERY: json.dumps({"Name": "Example CPU 4C", "NumberOfCores": 4}),
            host.WINDOWS_TOTAL_MEMORY_QUERY: str(16 * GIB),
            host.WINDOWS_MEMORY_QUERY: WINDOWS_MEMORY,
            host.WINDOWS_DISK_QUERY.format(letter="D"): json.dumps({"MediaType": "HDD", "BusType": "SATA"}),
        }
        monkeypatch.setattr(host, "powershell", replies.get)
        monkeypatch.setattr(host, "_windows_avx2", lambda: True)
        collected = host.collect_host(host.Path("D:/models"), system="win32")
        assert collected["cpu_model"] == ("Example CPU 4C", "Win32_Processor")
        assert collected["ram_total_bytes"] == (16 * GIB, "Win32_ComputerSystem")
        assert collected["ram_speed"] == ("3200 MT/s", "Win32_PhysicalMemory")
        assert collected["disk_type"] == ("SATA HDD", "Get-PhysicalDisk (D:)")
        assert collected["avx2"] == (True, "IsProcessorFeaturePresent")

    def test_linux_collection_reads_proc_and_resolves_the_disk(self, monkeypatch):
        files = {"/proc/cpuinfo": CPUINFO, "/proc/meminfo": "MemTotal: 16303916 kB\n"}
        commands = {
            "dmidecode": None,
            "findmnt": "/dev/nvme0n1p2\n",
            "lsblk": LSBLK_NVME,
        }
        monkeypatch.setattr(host, "_read", files.get)
        monkeypatch.setattr(host, "run_text", lambda argv, timeout=60.0: commands.get(argv[0]))
        collected = host.collect_host(host.Path("/var/lib/docker"), system="linux")
        assert collected["physical_cores"] == (2, "/proc/cpuinfo")
        assert collected["ram_total_bytes"] == (16303916 * 1024, "/proc/meminfo")
        assert collected["ram_speed"] == (None, "dmidecode")
        assert collected["disk_type"] == ("NVMe SSD", "lsblk (/dev/nvme0n1p2)")


class TestShell:
    def test_run_text_returns_stdout_or_none(self):
        shell = Shell()
        assert shell.run_text([sys.executable, "-c", "print('hello')"]).strip() == "hello"
        assert shell.run_text([sys.executable, "-c", "raise SystemExit(3)"]) is None
        assert shell.run_text(["hbk-no-such-program-here"]) is None

    def test_captured_output_and_exit_code(self):
        code, output = Shell().run_captured([sys.executable, "-c", "print('[1]'); raise SystemExit(2)"])
        assert (code, output.strip()) == (2, "[1]")

    def test_a_missing_program_is_reported_not_raised(self, capsys):
        assert Shell().run(["hbk-no-such-program-here"]) == COMMAND_NOT_STARTED
        assert Shell().run_captured(["hbk-no-such-program-here"]) == (COMMAND_NOT_STARTED, "")
        assert Shell().run_and_echo(["hbk-no-such-program-here"]) == (COMMAND_NOT_STARTED, [])
        assert "could not start hbk-no-such-program-here" in capsys.readouterr().out

    def test_a_product_shell_can_let_a_missing_program_raise(self, capsys):
        class StrictShell(Shell):
            start_errors = ()

        with pytest.raises(FileNotFoundError):
            StrictShell().run(["hbk-no-such-program-here"])
        with pytest.raises(FileNotFoundError):
            StrictShell().run_captured(["hbk-no-such-program-here"])
        assert StrictShell().run_and_echo(["hbk-no-such-program-here"]) == (COMMAND_NOT_STARTED, [])

    def test_run_and_echo_feeds_stdin_and_keeps_the_lines(self, capsys):
        code, lines = Shell().run_and_echo(
            [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"], stdin_text="probe job"
        )
        assert (code, lines) == (0, ["PROBE JOB"])
        assert capsys.readouterr().out.startswith("[info] ")

    def test_run_and_echo_prints_the_output_of_a_command_without_input(self, capsys):
        code, lines = Shell().run_and_echo([sys.executable, "-c", "print('[done] wrote x.json')"])
        assert (code, lines) == (0, ["[done] wrote x.json"])
        assert "[done] wrote x.json" in capsys.readouterr().out

    def test_docker_facts_and_git_commit_go_through_run_text(self):
        class Fake(Shell):
            def run_text(self, argv, timeout=60.0):
                return DOCKER_INFO if argv[0] == "docker" else "abc1234\n"

        assert Fake().docker_facts()["cpus"] == 12
        assert Fake().git_commit("anywhere") == "abc1234"
