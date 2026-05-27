try:
    from dmm_parser import *
    import dmm_parser as _dmm
    if not hasattr(_dmm, 'extract_file'):
        raise ImportError("dmm_parser missing native functions")
except ImportError as e:
    print(f"Error: {e}")
    from crimson_rs.crimson_rs import *
from crimson_rs.enums import Compression, Crypto, Language
