"""
Secrets Manager
===============
Simple secrets management for configuration.
Supports environment variables, files, and in-memory storage.
For production, consider using HashiCorp Vault or AWS Secrets Manager.
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import base64

logger = logging.getLogger(__name__)


class SecretsManager:
    """
    Simple secrets manager for development and small deployments.
    For production, integrate with proper secrets management systems.
    """
    
    def __init__(self, secrets_file: Optional[Path] = None):
        """
        Initialize secrets manager.
        
        Args:
            secrets_file: Path to secrets file (JSON format)
        """
        self.secrets_file = secrets_file or Path(__file__).parent.parent / "config" / "secrets.json"
        self.secrets: Dict[str, str] = {}
        self.load_secrets()
    
    def load_secrets(self):
        """Load secrets from file and environment"""
        # Load from file if exists
        if self.secrets_file and self.secrets_file.exists():
            try:
                with open(self.secrets_file, 'r') as f:
                    file_secrets = json.load(f)
                    self.secrets.update(file_secrets)
                logger.info(f"✅ Loaded secrets from {self.secrets_file}")
            except Exception as e:
                logger.warning(f"Failed to load secrets file: {e}")
        
        # Load from environment variables (prefixed with TRAFFIC_SECRET_)
        env_secrets = {
            k[16:]: v for k, v in os.environ.items()
            if k.startswith("TRAFFIC_SECRET_")
        }
        self.secrets.update(env_secrets)
        
        if env_secrets:
            logger.info(f"✅ Loaded {len(env_secrets)} secrets from environment")
    
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get secret value.
        
        Args:
            key: Secret key
            default: Default value if not found
            
        Returns:
            Secret value or default
        """
        # Check environment first (highest priority)
        env_key = f"TRAFFIC_SECRET_{key.upper()}"
        if env_key in os.environ:
            return os.environ[env_key]
        
        # Check loaded secrets
        if key in self.secrets:
            return self.secrets[key]
        
        # Check direct environment variable
        if key in os.environ:
            return os.environ[key]
        
        return default
    
    def set_secret(self, key: str, value: str, persist: bool = False):
        """
        Set secret value.
        
        Args:
            key: Secret key
            value: Secret value
            persist: Whether to persist to file
        """
        self.secrets[key] = value
        
        if persist and self.secrets_file:
            try:
                self.secrets_file.parent.mkdir(exist_ok=True, parents=True)
                with open(self.secrets_file, 'w') as f:
                    json.dump(self.secrets, f, indent=2)
                # Set restrictive permissions
                self.secrets_file.chmod(0o600)
                logger.info(f"✅ Secret saved to {self.secrets_file}")
            except Exception as e:
                logger.error(f"Failed to save secret: {e}")
    
    def get_jwt_secret(self) -> str:
        """Get JWT secret key"""
        secret = self.get_secret("JWT_SECRET_KEY")
        if not secret:
            # Generate a default secret (not secure for production!)
            import secrets
            secret = secrets.token_urlsafe(32)
            logger.warning("⚠️  Using auto-generated JWT secret (not secure for production!)")
        return secret
    
    def get_database_password(self) -> Optional[str]:
        """Get database password"""
        return self.get_secret("DATABASE_PASSWORD")
    
    def get_redis_password(self) -> Optional[str]:
        """Get Redis password"""
        return self.get_secret("REDIS_PASSWORD")
    
    def get_kafka_secret(self) -> Optional[str]:
        """Get Kafka secret"""
        return self.get_secret("KAFKA_SECRET")


# Global secrets manager instance
_secrets_manager: Optional[SecretsManager] = None


def get_secrets_manager(secrets_file: Optional[Path] = None) -> SecretsManager:
    """Get or create global secrets manager"""
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager(secrets_file=secrets_file)
    return _secrets_manager

