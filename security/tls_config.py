"""
TLS/SSL Configuration
=====================
TLS/SSL support for secure connections.
Supports both development (self-signed) and production (certificate-based) modes.
"""

import ssl
import logging
from pathlib import Path
from typing import Optional, Tuple
import subprocess

logger = logging.getLogger(__name__)


class TLSConfig:
    """
    TLS/SSL configuration manager.
    Supports self-signed certificates for development and real certificates for production.
    """
    
    def __init__(
        self,
        cert_file: Optional[Path] = None,
        key_file: Optional[Path] = None,
        ca_file: Optional[Path] = None,
        enable_tls: bool = False
    ):
        """
        Initialize TLS configuration.
        
        Args:
            cert_file: Path to certificate file
            key_file: Path to private key file
            ca_file: Path to CA certificate file (optional)
            enable_tls: Whether TLS is enabled
        """
        self.cert_file = cert_file
        self.key_file = key_file
        self.ca_file = ca_file
        self.enable_tls = enable_tls
        self.cert_dir = Path(__file__).parent.parent / "certs"
        self.cert_dir.mkdir(exist_ok=True)
    
    def generate_self_signed_cert(
        self,
        hostname: str = "localhost",
        days: int = 365,
        key_size: int = 2048
    ) -> Tuple[Path, Path]:
        """
        Generate self-signed certificate for development.
        
        Args:
            hostname: Hostname for certificate
            days: Certificate validity in days
            key_size: Key size in bits
            
        Returns:
            Tuple of (cert_file, key_file) paths
        """
        cert_file = self.cert_dir / "server.crt"
        key_file = self.cert_dir / "server.key"
        
        # Check if OpenSSL is available
        try:
            subprocess.run(["openssl", "version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("OpenSSL not found - cannot generate self-signed certificate")
            return cert_file, key_file
        
        # Generate certificate
        try:
            # Create certificate
            cmd = [
                "openssl", "req", "-x509", "-newkey", f"rsa:{key_size}",
                "-keyout", str(key_file),
                "-out", str(cert_file),
                "-days", str(days),
                "-nodes",  # No passphrase
                "-subj", f"/CN={hostname}"
            ]
            
            subprocess.run(cmd, capture_output=True, check=True)
            logger.info(f"✅ Self-signed certificate generated: {cert_file}")
            
            # Set permissions
            cert_file.chmod(0o644)
            key_file.chmod(0o600)
            
            return cert_file, key_file
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to generate certificate: {e}")
            raise
    
    def get_ssl_context(self) -> Optional[ssl.SSLContext]:
        """
        Get SSL context for server.
        
        Returns:
            SSL context if TLS enabled, None otherwise
        """
        if not self.enable_tls:
            return None
        
        # Use self-signed cert if no cert provided
        if not self.cert_file or not self.key_file:
            logger.info("No certificate provided, generating self-signed certificate...")
            self.cert_file, self.key_file = self.generate_self_signed_cert()
        
        # Check files exist
        if not self.cert_file.exists() or not self.key_file.exists():
            logger.warning("Certificate files not found, TLS disabled")
            return None
        
        # Create SSL context
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        
        try:
            context.load_cert_chain(
                str(self.cert_file),
                str(self.key_file)
            )
            
            # Load CA if provided
            if self.ca_file and self.ca_file.exists():
                context.load_verify_locations(str(self.ca_file))
            
            logger.info(f"✅ TLS enabled with certificate: {self.cert_file}")
            return context
            
        except Exception as e:
            logger.error(f"Failed to load certificate: {e}")
            return None
    
    def get_client_ssl_context(self, verify: bool = True) -> Optional[ssl.SSLContext]:
        """
        Get SSL context for client connections.
        
        Args:
            verify: Whether to verify server certificate
            
        Returns:
            SSL context for client
        """
        context = ssl.create_default_context()
        
        if not verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            logger.warning("⚠️  SSL verification disabled (development only)")
        
        # Load CA if provided
        if self.ca_file and self.ca_file.exists():
            context.load_verify_locations(str(self.ca_file))
        
        return context


def create_tls_config(
    cert_file: Optional[Path] = None,
    key_file: Optional[Path] = None,
    enable_tls: bool = False
) -> TLSConfig:
    """Create TLS configuration"""
    return TLSConfig(
        cert_file=cert_file,
        key_file=key_file,
        enable_tls=enable_tls
    )

