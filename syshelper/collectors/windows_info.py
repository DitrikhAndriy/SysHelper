"""Native Windows GPU collectors using system DLLs and the installed driver."""

import ctypes
from ctypes import wintypes
import os
import uuid
from threading import Lock

NVAPI_LOCK = Lock()


def _nvidia_memory(include_readings=False):
    with NVAPI_LOCK:
        return _nvidia_read(include_readings)


def _nvidia_read(include_readings=False):
    """Optional physical VRAM capacity from the installed NVIDIA driver."""
    class MemoryInfo(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint32) for name in
                    ("version", "dedicated", "available", "system", "shared", "free")]

    class Utilization(ctypes.Structure):
        _fields_ = [("present", ctypes.c_uint32), ("percentage", ctypes.c_uint32)]

    class DynamicStates(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint32), ("flags", ctypes.c_uint32), ("utilization", Utilization * 8)]

    class Clock(ctypes.Structure):
        _fields_ = [("present", ctypes.c_uint32), ("frequency", ctypes.c_uint32)]

    class Clocks(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint32), ("kind", ctypes.c_uint32), ("domains", Clock * 32)]

    library = "nvapi64.dll" if ctypes.sizeof(ctypes.c_void_p) == 8 else "nvapi.dll"
    path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", library)
    nvapi = ctypes.CDLL(path)
    nvapi.nvapi_QueryInterface.argtypes = [ctypes.c_uint32]
    nvapi.nvapi_QueryInterface.restype = ctypes.c_void_p

    def function(identifier, *arguments):
        address = nvapi.nvapi_QueryInterface(identifier)
        if not address:
            raise OSError(f"NVAPI interface unavailable: 0x{identifier:08X}")
        return ctypes.CFUNCTYPE(ctypes.c_int, *arguments)(address)

    def check(status):
        if status:
            raise OSError(f"NVAPI status: {status}")

    check(function(0x0150E828)())
    try:
        handles = (ctypes.c_void_p * 64)()
        count = ctypes.c_uint32()
        check(function(0xE5AC921F, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32))(
            handles, ctypes.byref(count)))
        get_name = function(0xCEEE8E9F, ctypes.c_void_p, ctypes.c_char_p)
        get_memory = function(0x07F9B368, ctypes.c_void_p, ctypes.POINTER(MemoryInfo))
        rows = []
        for handle in handles[:count.value]:
            name = ctypes.create_string_buffer(64)
            check(get_name(handle, name))
            memory = MemoryInfo()
            memory.version = ctypes.sizeof(memory) | (2 << 16)
            check(get_memory(handle, ctypes.byref(memory)))
            item = {"Name": name.value.decode("utf-8", errors="replace"),
                         "Dedicated": memory.dedicated * 1024,
                         "Usable": memory.available * 1024}
            if include_readings:
                item["VRAMUsed"] = max(0, memory.available - memory.free) * 1024
                item["ReadingErrors"] = []
                for identifier, structure, version, field in (
                    (0x60DED2ED, DynamicStates, 1, "Usage"),
                    (0xDCB616C3, Clocks, 3, "Clocks"),
                ):
                    try:
                        info = structure()
                        info.version = ctypes.sizeof(info) | (version << 16)
                        check(function(identifier, ctypes.c_void_p, ctypes.POINTER(structure))(handle, ctypes.byref(info)))
                        if field == "Usage" and info.utilization[0].present & 1:
                            item[field] = info.utilization[0].percentage
                        elif field == "Clocks":
                            for label, index in (("CoreClock", 0), ("MemoryClock", 4)):
                                if info.domains[index].present & 1:
                                    item[label] = info.domains[index].frequency / 1000
                    except OSError as error:
                        item["ReadingErrors"].append(f"{field}: {error}")
                try:
                    rpm = ctypes.c_uint32()
                    check(function(0x5F608315, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))(handle, ctypes.byref(rpm)))
                    item["FanRPM"] = rpm.value
                except OSError as error:
                    item["ReadingErrors"].append(f"Fan: {error}")
            rows.append(item)
        return rows
    finally:
        function(0xD22BDD7E)()


def gpu_inventory(include_readings=False):
    """Read true adapter memory capacities through DXGI, including cards over 4 GB."""
    class Guid(ctypes.Structure):
        _fields_ = [("bytes", ctypes.c_ubyte * 16)]

    class Luid(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class AdapterDesc(ctypes.Structure):
        _fields_ = [("Description", wintypes.WCHAR * 128), ("VendorId", wintypes.UINT),
                    ("DeviceId", wintypes.UINT), ("SubSysId", wintypes.UINT),
                    ("Revision", wintypes.UINT), ("DedicatedVideoMemory", ctypes.c_size_t),
                    ("DedicatedSystemMemory", ctypes.c_size_t), ("SharedSystemMemory", ctypes.c_size_t),
                    ("AdapterLuid", Luid), ("Flags", wintypes.UINT)]

    def method(pointer, slot, result, *arguments):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *arguments)(table[slot])

    def check(hresult, operation):
        if hresult < 0:
            raise OSError(f"{operation}: HRESULT 0x{hresult & 0xFFFFFFFF:08X}")

    iid = Guid()
    ctypes.memmove(ctypes.byref(iid), uuid.UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le, 16)
    dxgi = ctypes.WinDLL("dxgi")
    dxgi.CreateDXGIFactory1.argtypes = [ctypes.POINTER(Guid), ctypes.POINTER(ctypes.c_void_p)]
    dxgi.CreateDXGIFactory1.restype = wintypes.LONG
    factory = ctypes.c_void_p()
    check(dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)), "CreateDXGIFactory1")
    rows = []
    try:
        enum = method(factory, 12, wintypes.LONG, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            result = enum(factory, index, ctypes.byref(adapter))
            if result & 0xFFFFFFFF == 0x887A0002:  # DXGI_ERROR_NOT_FOUND: end of enumeration.
                break
            check(result, "EnumAdapters1")
            index += 1
            try:
                desc = AdapterDesc()
                check(method(adapter, 10, wintypes.LONG, ctypes.POINTER(AdapterDesc))(
                    adapter, ctypes.byref(desc)), "GetDesc1")
                if desc.Flags & 2:  # Software renderer, not a physical GPU.
                    continue
                rows.append({"Name": desc.Description, "Dedicated": desc.DedicatedVideoMemory,
                             "Shared": desc.SharedSystemMemory, "Vendor": desc.VendorId,
                             "CapacityKind": "usable"})
            finally:
                method(adapter, 2, wintypes.ULONG)(adapter)
    finally:
        method(factory, 2, wintypes.ULONG)(factory)
    if any(row["Vendor"] == 0x10DE for row in rows):
        try:
            memory_rows = _nvidia_memory(include_readings)
            for row in rows:
                normalize = lambda name: name.casefold().removeprefix("nvidia ").strip()
                matches = [info for info in memory_rows if normalize(info["Name"]) == normalize(row["Name"])]
                same_model = sum(normalize(other["Name"]) == normalize(row["Name"]) for other in rows)
                if len(matches) == 1 and same_model == 1:
                    row.update({key: item for key, item in matches[0].items() if key != "Name"})
                    row["CapacityKind"] = "physical"
        except OSError as error:
            for row in rows:
                if row["Vendor"] == 0x10DE:
                    row["Error"] = str(error)
    return rows
