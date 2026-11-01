# Build on Windows x64: python -m PyInstaller --noconfirm AlbionTradeDesk.spec
from PyInstaller.utils.hooks import collect_data_files

a = Analysis(['launcher.py'], pathex=['.'], binaries=[],
             datas=collect_data_files('albion_trade_desk'), hiddenimports=[],
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='AlbionTradeDesk',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
