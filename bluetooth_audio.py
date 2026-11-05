"""Ask Windows to reconnect a paired Bluetooth speaker, and make it the default output.

A PC waking from sleep doesn't bring a Bluetooth speaker back by itself, so the morning alarm does it.
Reconnecting can't power on a speaker that has switched itself off; connect() returns False then.
Both calls use the interfaces Windows' own sound settings use (IKsControl one-shot reconnect, IPolicyConfig).
"""
import ctypes
import time
from ctypes import HRESULT, POINTER, byref, c_ulong, c_void_p, c_wchar_p
from ctypes.wintypes import DWORD, LPCWSTR, UINT

import comtypes
from comtypes import COMMETHOD, GUID, IUnknown
from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
from pycaw.constants import CLSID_MMDeviceEnumerator, DEVICE_STATE, EDataFlow
from pycaw.pycaw import AudioUtilities

KSPROPSETID_BT_AUDIO = GUID('{7FA06C40-B8F6-4C7E-8556-E8C33A12E54D}')
KSPROPERTY_ONESHOT_RECONNECT = 0
KSPROPERTY_TYPE_GET = 1
CLSCTX_ALL = 23
CLSID_POLICY_CONFIG = GUID('{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}')


def _unused(count):
    """Placeholders: a COM method is called by its position in the interface, so earlier ones must be declared."""
    return [COMMETHOD([], HRESULT, f'Unused{n}') for n in range(count)]


class KSPROPERTY(ctypes.Structure):
    _fields_ = [('Set', GUID), ('Id', c_ulong), ('Flags', c_ulong)]


class IKsControl(IUnknown):
    _iid_ = GUID('{28F54685-06FD-11D2-B27A-00A0C9223196}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'KsProperty', (['in'], POINTER(KSPROPERTY), 'prop'), (['in'], c_ulong, 'prop_size'),
                  (['in'], c_void_p, 'data'), (['in'], c_ulong, 'data_size'),
                  (['out'], POINTER(c_ulong), 'returned')),
    ]


class IConnector(IUnknown):
    _iid_ = GUID('{9C2C4058-23F5-41DE-877A-DF3AF236A09E}')
    _methods_ = _unused(7) + [
        COMMETHOD([], HRESULT, 'GetDeviceIdConnectedTo', (['out'], POINTER(c_wchar_p), 'device_id')),
    ]


class IDeviceTopology(IUnknown):
    _iid_ = GUID('{2A07407E-6497-4A18-9787-32F79BD0D98F}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'GetConnectorCount', (['out'], POINTER(UINT), 'count')),
        COMMETHOD([], HRESULT, 'GetConnector', (['in'], UINT, 'index'), (['out'], POINTER(POINTER(IUnknown)), 'out')),
    ]


class IPolicyConfig(IUnknown):
    """Undocumented but long stable: the "Set as default" button in Windows' sound settings."""
    _iid_ = GUID('{F8679F50-850A-41CF-9C72-430F290290C8}')
    _methods_ = _unused(10) + [
        COMMETHOD([], HRESULT, 'SetDefaultEndpoint', (['in'], LPCWSTR, 'device_id'), (['in'], DWORD, 'role')),
    ]


def _com():
    # Never paired with CoUninitialize: the COM objects here are released later, by garbage collection, and
    # releasing one after uninitializing crashes the process. These run on Jarvis's long-lived alarm thread.
    comtypes.CoInitialize()


def _find(name, state):
    wanted = name.casefold()
    devices = AudioUtilities.GetAllDevices(data_flow=EDataFlow.eRender.value, device_state=state)
    return next((d for d in devices if d.FriendlyName and wanted in d.FriendlyName.casefold()), None)


def connected(name):
    """Whether Windows has this speaker as a live output right now."""
    _com()
    return _find(name, DEVICE_STATE.ACTIVE.value) is not None


def request_reconnect(name):
    """Send the one-shot reconnect to the speaker's Bluetooth driver. False if there's no such paired endpoint."""
    _com()
    device = _find(name, DEVICE_STATE.MASK_ALL.value)
    if device is None:
        return False
    enumerator = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)
    topology = device._dev.Activate(IDeviceTopology._iid_, CLSCTX_ALL, None).QueryInterface(IDeviceTopology)
    for index in range(topology.GetConnectorCount()):
        driver_id = topology.GetConnector(index).QueryInterface(IConnector).GetDeviceIdConnectedTo()
        control = enumerator.GetDevice(driver_id).Activate(IKsControl._iid_, CLSCTX_ALL, None).QueryInterface(IKsControl)
        prop = KSPROPERTY(KSPROPSETID_BT_AUDIO, KSPROPERTY_ONESHOT_RECONNECT, KSPROPERTY_TYPE_GET)
        control.KsProperty(byref(prop), ctypes.sizeof(prop), None, 0)
    return True


def set_default(name):
    """Make the speaker the Windows default output, so Spotify plays on it. False if it isn't connected."""
    _com()
    device = _find(name, DEVICE_STATE.ACTIVE.value)
    if device is None:
        return False
    policy = comtypes.CoCreateInstance(CLSID_POLICY_CONFIG, IPolicyConfig)
    for role in (0, 1):  # console and multimedia; "communications" would pull calls onto the speaker
        policy.SetDefaultEndpoint(device.id, role)
    return True


def connect(name, attempts=3, wait=8, sleep=time.sleep):
    """Try to bring the speaker up. True once Windows has it as a live output."""
    if connected(name):
        return True
    for _ in range(attempts):
        try:
            request_reconnect(name)
        except Exception as e:
            print(f"(Bluetooth reconnect failed: {e})", flush=True)
        sleep(wait)
        if connected(name):
            return True
    return False
