"""Vendored ``xml.etree`` (``ElementTree`` + ``ElementPath``) — see ``_vendor/README.md``.

Decky Loader's PyInstaller-frozen Python does not bundle the ``xml.etree``
package (``adapters/es_de_config.py`` already routes around this for the
plugin's own ES-DE parsing, using ``xml.parsers.expat`` directly). The
vendored emu-atlas package imports ``xml.etree.ElementTree`` for its own
ES-DE catalogue parsing; rather than hand-rewriting that parsing to expat
inside third-party code, this vendors the two CPython stdlib modules
``ElementTree`` builds on ``xml.parsers.expat`` for the pure-Python path
(``ElementTree.py``, ``ElementPath.py``) so the import resolves under
``_vendor.elementtree`` instead of the frozen interpreter's own (absent)
``xml.etree``. Both modules degrade to their pure-Python implementation when
the ``_elementtree`` C accelerator is unavailable — which it also is not in
the frozen build — so this is not merely present but exercised.
"""
