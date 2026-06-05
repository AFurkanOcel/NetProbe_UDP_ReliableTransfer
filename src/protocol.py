# =============================================================
# protocol.py — NetProbe Paket Protokolü
#
# DATA Paketi Yapısı (struct format: !BII I 32s {payload_len}s):
#   [1B]  packet_type      : 0x01 = DATA
#   [4B]  sequence_number  : Paketin sıra numarası (0'dan başlar)
#   [4B]  total_packets    : Toplam kaç paket gönderileceği
#   [4B]  payload_length   : Payload kaç byte
#   [32B] checksum         : SHA-256 (payload'un hash'i)
#   [?B]  payload          : Dosya verisi
#
# ACK Paketi Yapısı (struct format: !BII):
#   [1B]  packet_type      : 0x02 = ACK
#   [4B]  ack_number       : Hangi paket numarası onaylandı
#   [4B]  (reserved)       : İleride kullanım için
#
# FIN Paketi Yapısı (struct format: !B32s):
#   [1B]  packet_type      : 0x03 = FIN
#   [32B] file_checksum    : Tüm dosyanın SHA-256 hash'i
# =============================================================

import struct
import hashlib
from config import PACKET_TYPE_DATA, PACKET_TYPE_ACK, PACKET_TYPE_FIN

# --- Sabitler ---
DATA_HEADER_FORMAT = "!B I I I 32s"  # ! = big-endian, B=1B, I=4B, 32s=32B
DATA_HEADER_SIZE   = struct.calcsize(DATA_HEADER_FORMAT)  # 45 byte

ACK_FORMAT         = "!B I I"
ACK_SIZE           = struct.calcsize(ACK_FORMAT)          # 9 byte

FIN_FORMAT         = "!B 32s"
FIN_SIZE           = struct.calcsize(FIN_FORMAT)          # 33 byte


# ============================================================
# Checksum Hesaplama
# ============================================================

def compute_checksum(data: bytes) -> bytes:
    """
    Verilen byte dizisinin SHA-256 hash'ini döner (32 byte).
    Checksum: payload bütünlüğünü doğrulamak için kullanılır.
    """
    return hashlib.sha256(data).digest()


def verify_checksum(data: bytes, expected_checksum: bytes) -> bool:
    """Checksum doğrulaması. True = veri bozulmamış."""
    return compute_checksum(data) == expected_checksum


# ============================================================
# Veri Paketi (DATA)
# ============================================================

def create_data_packet(seq_num: int, total_packets: int, payload: bytes) -> bytes:
    """
    Verilen payload için bir DATA paketi oluşturur.
    
    Args:
        seq_num       : Bu paketin sıra numarası (0-indexed)
        total_packets : Toplam paket sayısı
        payload       : Gönderilecek ham veri (bytes)
    
    Returns:
        bytes: Paketlenmiş ham byte dizisi (header + payload)
    """
    checksum = compute_checksum(payload)
    header = struct.pack(
        DATA_HEADER_FORMAT,
        PACKET_TYPE_DATA,   # packet_type
        seq_num,            # sequence_number
        total_packets,      # total_packets
        len(payload),       # payload_length
        checksum            # checksum (32 byte)
    )
    return header + payload


def parse_data_packet(raw: bytes) -> dict | None:
    """
    Ham byte dizisini parse ederek DATA paketini sözlüğe dönüştürür.
    Checksum hatası veya yanlış tip → None döner.
    
    Returns:
        dict: {packet_type, seq_num, total_packets, payload_length, checksum, payload, valid}
        None: Ayrıştırma başarısız
    """
    if len(raw) < DATA_HEADER_SIZE:
        return None
    try:
        ptype, seq_num, total, plen, checksum = struct.unpack(
            DATA_HEADER_FORMAT, raw[:DATA_HEADER_SIZE]
        )
        if ptype != PACKET_TYPE_DATA:
            return None
        payload = raw[DATA_HEADER_SIZE:DATA_HEADER_SIZE + plen]
        if len(payload) != plen:
            return None
        valid = verify_checksum(payload, checksum)
        return {
            "packet_type"   : ptype,
            "seq_num"       : seq_num,
            "total_packets" : total,
            "payload_length": plen,
            "checksum"      : checksum,
            "payload"       : payload,
            "valid"         : valid       # False ise veri bozuk
        }
    except struct.error:
        return None


# ============================================================
# ACK Paketi
# ============================================================

def create_ack_packet(ack_num: int) -> bytes:
    """
    Verilen sequence numarası için ACK paketi oluşturur.
    
    Args:
        ack_num : Onaylanan paketin seq_num'u
    
    Returns:
        bytes: ACK paketi
    """
    return struct.pack(ACK_FORMAT, PACKET_TYPE_ACK, ack_num, 0)


def parse_ack_packet(raw: bytes) -> dict | None:
    """
    ACK paketini parse eder.
    
    Returns:
        dict: {packet_type, ack_num}
        None: Başarısız
    """
    if len(raw) < ACK_SIZE:
        return None
    try:
        ptype, ack_num, _ = struct.unpack(ACK_FORMAT, raw[:ACK_SIZE])
        if ptype != PACKET_TYPE_ACK:
            return None
        return {"packet_type": ptype, "ack_num": ack_num}
    except struct.error:
        return None


# ============================================================
# FIN Paketi (Aktarım Sonu)
# ============================================================

def create_fin_packet(file_checksum: bytes) -> bytes:
    """
    Aktarım sonu sinyali. Tüm dosyanın checksum'ını içerir.
    Sunucu bu paketi alınca dosyanın tamamının hash'ini doğrular.
    
    Args:
        file_checksum : Tüm dosyanın SHA-256 hash'i (32 byte)
    
    Returns:
        bytes: FIN paketi
    """
    return struct.pack(FIN_FORMAT, PACKET_TYPE_FIN, file_checksum)


def parse_fin_packet(raw: bytes) -> dict | None:
    """
    FIN paketini parse eder.
    
    Returns:
        dict: {packet_type, file_checksum}
        None: Başarısız
    """
    if len(raw) < FIN_SIZE:
        return None
    try:
        ptype, file_checksum = struct.unpack(FIN_FORMAT, raw[:FIN_SIZE])
        if ptype != PACKET_TYPE_FIN:
            return None
        return {"packet_type": ptype, "file_checksum": file_checksum}
    except struct.error:
        return None


# ============================================================
# Genel: Paketi Türüne Göre Tanı
# ============================================================

def identify_packet(raw: bytes) -> str:
    """Ham paketin tipini döner: 'DATA', 'ACK', 'FIN' veya 'UNKNOWN'."""
    if not raw:
        return "UNKNOWN"
    ptype = raw[0]
    if ptype == PACKET_TYPE_DATA:
        return "DATA"
    elif ptype == PACKET_TYPE_ACK:
        return "ACK"
    elif ptype == PACKET_TYPE_FIN:
        return "FIN"
    return "UNKNOWN"


def compute_file_checksum(filepath: str) -> bytes:
    """Bir dosyanın tamamını okuyarak SHA-256 hash'ini döner."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.digest()
