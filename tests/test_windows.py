import os
import sys

import pytest

from mnemo.windows import parse_hotkey, WindowsHotkey, WindowsAutostart, startup_command


@pytest.mark.parametrize('value', ['', 'M', 'Ctrl+Ctrl+M', 'Ctrl+Alt+Space', 'Ctrl+F25', 'Ctrl+М'])
def test_invalid_hotkeys(value):
    with pytest.raises(ValueError):
        parse_hotkey(value)


def test_key_parsing_and_no_repeat():
    assert parse_hotkey('Ctrl+Alt+M') == (0x4003, ord('M'))
    assert parse_hotkey('Win+Shift+F24') == (0x400C, 0x87)


@pytest.mark.skipif(os.name != 'nt', reason='Windows adapter')
def test_registry_adapter_only_changes_named_value(monkeypatch):
    import winreg
    values = {}
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def query(key, name):
        if name not in values:
            raise FileNotFoundError
        return values[name], winreg.REG_SZ
    monkeypatch.setattr(winreg, 'OpenKey', lambda *args: Key())
    monkeypatch.setattr(winreg, 'CreateKeyEx', lambda *args: Key())
    monkeypatch.setattr(winreg, 'QueryValueEx', query)
    monkeypatch.setattr(winreg, 'SetValueEx', lambda key, name, unused, kind, value: values.update({name: value}))
    def delete(key, name):
        if name not in values: raise FileNotFoundError
        del values[name]
    monkeypatch.setattr(winreg, 'DeleteValue', delete)
    values['Another app'] = 'untouched'
    backend = WindowsAutostart()
    assert not backend.enabled()
    backend.set_enabled(True)
    assert backend.enabled()
    assert '--autostart' in values['Mnemo'] and '--data-dir' in values['Mnemo']
    backend.set_enabled(False)
    backend.set_enabled(False)
    assert values == {'Another app': 'untouched'}


@pytest.mark.skipif(os.name != 'nt', reason='Windows adapter')
def test_native_registration_change_and_conflict_preserve_old_key():
    first, second = WindowsHotkey(), WindowsHotkey()
    try:
        # An uncommon combination, held only within the test and always released.
        try:
            first.register('Ctrl+Alt+Shift+F23')
        except OSError:
            pytest.skip('Test hotkey already used by another application')
        with pytest.raises(OSError):
            second.register('Ctrl+Alt+Shift+F23')
        assert first.registration_id is not None
        assert second.registration_id is None
        with pytest.raises(ValueError):
            first.register('unsupported')
        assert first.current == 'Ctrl+Alt+Shift+F23'
    finally:
        first.close()
        second.close()


def test_frozen_startup_command_quotes_executable_and_data_path(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'a folder' / 'Mnemo.exe'))
    monkeypatch.setenv('MNEMO_DATA_DIR', str(tmp_path / 'user data'))
    command = startup_command()
    assert command.startswith('"')
    assert 'Mnemo.exe" --autostart --data-dir "' in command
