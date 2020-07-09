import binascii
import struct
from io import BytesIO
from typing import Union, List

from WADGEN import Base, Signature, Certificate, ROOT_KEY, utils, DSI_KEY, DECRYPTION_KEYS


class Ticket(Base):
    def __init__(self, f: Union[str, bytes, bytearray, None] = None):
        self.signature = Signature(sigtype=65537)
        self.issuer = b"\x00" * 64
        self.ecdhdata = b"\x00" * 60
        self.unused1 = b"\x00" * 3
        self.titlekey = b"\x00" * 16
        self.unknown1 = b"\x00"
        self.ticketid = b"\x00" * 8
        self.consoleid = 0
        self.titleid = 0
        self.unknown2 = b"\x00" * 2
        self.titleversion = 0
        self.permitted_titles_mask = 0
        self.permit_mask = 0
        self.export_allowed = False
        self.ckeyindex = 0
        self.unknown3 = b"\x00" * 48
        self.content_access_permissions = b"\x00" * 64
        self.padding = 0
        self.limits = b"\x00" * 64
        self.certificates = [Certificate(sigtype=0x10001, keytype=1), Certificate(sigtype=0x10000, keytype=1)]

        super().__init__(f)

    def parse(self, f: BytesIO):
        f.seek(0)
        self.signature = Signature(f)
        self.issuer = f.read(64)
        self.ecdhdata = f.read(60)
        self.unused1 = f.read(3)
        self.titlekey = f.read(16)
        self.unknown1 = f.read(1)
        self.ticketid = f.read(8)
        self.consoleid = struct.unpack(">L", f.read(4))[0]
        self.titleid = struct.unpack(">Q", f.read(8))[0]
        self.unknown2 = f.read(2)
        self.titleversion = struct.unpack(">H", f.read(2))[0]
        self.permitted_titles_mask = struct.unpack(">L", f.read(4))[0]
        self.permit_mask = struct.unpack(">L", f.read(4))[0]
        self.export_allowed = struct.unpack(">?", f.read(1))[0]
        self.ckeyindex = struct.unpack(">B", f.read(1))[0]
        self.unknown3 = f.read(48)
        self.content_access_permissions = f.read(64)
        self.padding = struct.unpack(">H", f.read(2))[0]
        self.limits = f.read(64)

        self.certificates = []
        for i in range(2):
            self.certificates.append(Certificate(f))

    def pack(self, include_signature=True, include_certificates=False) -> bytes:
        pack = b""
        if include_signature:
            pack += self.signature.pack()
        pack += self.issuer
        pack += self.ecdhdata
        pack += self.unused1
        pack += self.titlekey
        pack += self.unknown1
        pack += self.ticketid
        pack += struct.pack(">L", self.consoleid)
        pack += struct.pack(">Q", self.titleid)
        pack += self.unknown2
        pack += struct.pack(">H", self.titleversion)
        pack += struct.pack(">L", self.permitted_titles_mask)
        pack += struct.pack(">L", self.permit_mask)
        pack += struct.pack(">?", self.export_allowed)
        pack += struct.pack(">B", self.ckeyindex)
        pack += self.unknown3
        pack += self.content_access_permissions
        pack += struct.pack(">H", self.padding)
        pack += self.limits  # TODO: How to parse this?

        if include_certificates:
            for cert in self.certificates:
                pack += cert.pack()

        return pack

    def dump(self, output, include_signature=True, include_certificates=True) -> str:
        """Dumps TMD to output. Replaces {titleid} and {titleversion} if in path.
           Returns the file path.
        """
        output = output.format(titleid=self.get_titleid(), titleversion=self.get_titleversion())
        pack = self.pack(include_signature=include_signature, include_certificates=include_certificates)
        with open(output, "wb") as file:
            file.write(pack)
        return output

    def get_signature(self) -> Signature:
        return self.signature

    def get_certificates(self) -> List[Certificate]:
        return self.certificates

    def get_certificate(self, i: int) -> Certificate:
        return self.get_certificates()[i]

    def get_issuers(self) -> List[str]:
        """Returns list with the certificate chain issuers.
           There should be exactly three: the last one (XS) signs the Ticket,
           the one before that (CA) signs the CP cert and
           the first one (Root) signs the CA cert.
        """
        return self.issuer.rstrip(b"\00").decode().split("-")

    def get_titleid(self) -> str:
        return "{:08X}".format(self.titleid).zfill(16).lower()

    def get_titleversion(self) -> int:
        return self.titleversion

    def get_iv(self) -> bytes:
        return struct.pack(">Q", self.titleid) + b"\x00" * 8

    def get_iv_hex(self) -> str:
        return binascii.hexlify(self.get_iv()).decode()

    def get_consoleid(self) -> int:
        return self.consoleid

    def get_cert_by_name(self, name) -> Certificate:
        """Returns certificate by name."""
        for cert in self.get_certificates():
            if cert.get_name() == name:
                return cert
        if name == "Root":
            if ROOT_KEY:
                return ROOT_KEY
        raise ValueError("Certificate '{0}' not found.".format(name))

    def get_decryption_key(self) -> bytes:
        # TODO: Debug (RVT) Tickets
        """Returns the appropiate Common Key"""
        if self.get_titleid().startswith("00030"):
            return DSI_KEY
        try:
            return DECRYPTION_KEYS[self.ckeyindex]
        except IndexError:
            print("WARNING: Unknown Common Key, assuming normal key")
            return DECRYPTION_KEYS[0]

    def get_common_key_type(self) -> str:
        if self.get_titleid().startswith("00030"):
            return "DSi"
        key_types = [
            "Normal",
            "Korean",
            "Wii U Wii Mode"
        ]
        try:
            return key_types[self.ckeyindex]
        except IndexError:
            return "Unknown"

    def get_encrypted_titlekey(self) -> bytes:
        return self.titlekey

    def get_encrypted_titlekey_hex(self) -> str:
        return binascii.hexlify(self.titlekey).decode()

    def get_decrypted_titlekey(self) -> bytes:
        return utils.Crypto.decrypt_titlekey(
                commonkey=self.get_decryption_key(),
                iv=self.get_iv(),
                titlekey=self.get_encrypted_titlekey()
        )

    def get_decrypted_titlekey_hex(self) -> str:
        return binascii.hexlify(self.get_decrypted_titlekey()).decode()

    def set_titleid(self, tid: str):
        if not isinstance(tid, str):
            raise Exception("String expected.")

        if len(tid) != 16:
            raise ValueError("Title ID must be 16 characters long.")
        val = int(tid, 16)
        self.titleid = val

    def set_titleversion(self, ver: int):
        if not isinstance(ver, int):
            raise Exception("Integer expected.")

        if not 0 <= ver <= 65535:
            raise Exception("Invalid title version.")
        self.titleversion = ver

    def set_common_key_index(self, i: int):
        if not isinstance(i, int):
            raise Exception("Integer expected.")

        if not 0 <= i <= 2:
            raise Exception("Invalid Common-Key index!")
        self.ckeyindex = i

    def set_titlekey(self, key: str, encrypted: bool = True):
        """encrypted = False will encrypt the titlekey beforehand."""
        if not isinstance(key, str):
            raise Exception("String expected.")

        if len(key) != 32:
            raise Exception("Key must be 32 characters long.")

        if not encrypted:
            key = utils.Crypto.encrypt_titlekey(
                    self.get_decryption_key(),
                    self.get_iv(),
                    binascii.a2b_hex(key)
            )
        self.titlekey = binascii.a2b_hex(key)

    def fakesign(self):
        """Fakesigns Ticket.
           https://github.com/FIX94/Some-YAWMM-Mod/blob/e2708863036066c2cc8bad1fc142e90fb8a0464d/source/title.c#L22-L48
        """
        oldval = self.padding
        self.signature.zerofill()
        for i in range(65535):  # Max value for unsigned short integer (2 bytes)
            # Modify unused data
            self.padding = i

            # Calculate hash
            sha1hash = utils.Crypto.create_sha1hash_hex(self.pack(include_signature=False))

            # Found valid hash!
            if sha1hash.startswith("00"):
                return

        self.padding = oldval
        raise Exception("Fakesigning failed.")

    def __repr__(self):
        return "<Ticket(titleid='{id}', titleversion='{ver}', commonkey='{ckey}')>".format(
                id=self.get_titleid(),
                ver=self.get_titleversion(),
                ckey=self.get_common_key_type()
        )

    def __str__(self):
        output = "Ticket:\n"
        output += "  Title ID: {0}\n".format(self.get_titleid())
        output += "  Ticket Title Version: {0}\n".format(self.get_titleversion())
        if self.get_consoleid():
            output += "  Console ID: {0}\n".format(self.get_consoleid())
        output += "\n"
        output += "  Common Key: {0}\n".format(self.get_common_key_type())
        output += "  Initialization vector: {0}\n".format(self.get_iv_hex())
        output += "  Title key (encrypted): {0}\n".format(self.get_encrypted_titlekey_hex())
        output += "  Title key (decrypted): {0}\n".format(self.get_decrypted_titlekey_hex())

        # TODO: Certificates + signing stuff here

        return output
