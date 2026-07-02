"""
License Plate Validation Module for ATMS
Validates and formats license plate text according to regional standards
"""

import re
from typing import List, Dict, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
import time
import logging
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

class PlateFormat(Enum):
    """License plate formats"""
    US_STANDARD = "us_standard"
    US_CALIFORNIA = "us_california"
    US_NEW_YORK = "us_new_york"
    UK_STANDARD = "uk_standard"
    EU_STANDARD = "eu_standard"
    UNKNOWN = "unknown"

class ValidationResult(Enum):
    """Validation results"""
    VALID = "valid"
    INVALID = "invalid"
    SUSPICIOUS = "suspicious"
    UNKNOWN = "unknown"

@dataclass
class PlateValidation:
    """License plate validation result"""
    is_valid: bool
    confidence: float
    format_detected: PlateFormat
    validation_result: ValidationResult
    suggestions: List[str]
    country: str
    region: str
    timestamp: float

class LicensePlateValidator:
    """
    License plate validator with support for multiple formats
    Validates text according to regional standards
    """
    
    def __init__(self, 
                 supported_countries: List[str] = None,
                 strict_validation: bool = True):
        """
        Initialize license plate validator
        
        Args:
            supported_countries: List of supported countries
            strict_validation: Use strict validation rules
        """
        self.supported_countries = supported_countries or ["US", "UK", "EU"]
        self.strict_validation = strict_validation
        
        # Initialize format patterns
        self.format_patterns = self._initialize_format_patterns()
        
        # Performance tracking
        self.validation_times = deque(maxlen=100)
        self.total_validations = 0
        self.valid_plates = 0
        self.invalid_plates = 0
        
        logger.info(f"License Plate Validator initialized: {self.supported_countries}")
    
    def _initialize_format_patterns(self) -> Dict[str, Dict]:
        """Initialize format patterns for different countries"""
        patterns = {
            "US": {
                "standard": r"^[A-Z]{1,3}[0-9]{1,4}[A-Z]{0,2}$",
                "california": r"^[0-9]{1}[A-Z]{3}[0-9]{3}$",
                "new_york": r"^[A-Z]{3}[0-9]{4}$",
                "texas": r"^[A-Z]{3}[0-9]{4}$",
                "florida": r"^[A-Z]{3}[0-9]{3}$"
            },
            "UK": {
                "standard": r"^[A-Z]{2}[0-9]{2}[A-Z]{3}$",
                "old_format": r"^[A-Z]{1,3}[0-9]{1,4}[A-Z]{0,2}$"
            },
            "EU": {
                "standard": r"^[A-Z]{1,3}[0-9]{1,4}[A-Z]{0,2}$",
                "german": r"^[A-Z]{1,3}[A-Z]{1,2}[0-9]{1,4}[A-Z]{0,2}$",
                "french": r"^[0-9]{4}[A-Z]{2}[0-9]{2}$"
            }
        }
        
        return patterns
    
    def validate_plate(self, plate_text: str, country: str = None) -> PlateValidation:
        """
        Validate license plate text
        
        Args:
            plate_text: License plate text to validate
            country: Specific country to validate against
        
        Returns:
            Plate validation result
        """
        start_time = time.time()
        
        if not plate_text or len(plate_text.strip()) == 0:
            return PlateValidation(
                is_valid=False,
                confidence=0.0,
                format_detected=PlateFormat.UNKNOWN,
                validation_result=ValidationResult.INVALID,
                suggestions=[],
                country="",
                region="",
                timestamp=time.time()
            )
        
        # Clean text
        cleaned_text = self._clean_plate_text(plate_text)
        
        if not cleaned_text:
            return PlateValidation(
                is_valid=False,
                confidence=0.0,
                format_detected=PlateFormat.UNKNOWN,
                validation_result=ValidationResult.INVALID,
                suggestions=["Invalid characters detected"],
                country="",
                region="",
                timestamp=time.time()
            )
        
        # Detect format and country
        format_detected, detected_country, region = self._detect_format(cleaned_text, country)
        
        # Validate against detected format
        is_valid, confidence, suggestions = self._validate_against_format(
            cleaned_text, format_detected, detected_country
        )
        
        # Determine validation result
        if is_valid and confidence >= 0.8:
            validation_result = ValidationResult.VALID
        elif is_valid and confidence >= 0.5:
            validation_result = ValidationResult.SUSPICIOUS
        else:
            validation_result = ValidationResult.INVALID
        
        # Update metrics
        processing_time = time.time() - start_time
        self.validation_times.append(processing_time)
        self.total_validations += 1
        
        if is_valid:
            self.valid_plates += 1
        else:
            self.invalid_plates += 1
        
        logger.debug(f"Plate validation: '{cleaned_text}' -> {validation_result.value} (confidence: {confidence:.2f}) in {processing_time*1000:.2f}ms")
        
        return PlateValidation(
            is_valid=is_valid,
            confidence=confidence,
            format_detected=format_detected,
            validation_result=validation_result,
            suggestions=suggestions,
            country=detected_country,
            region=region,
            timestamp=time.time()
        )
    
    def _clean_plate_text(self, text: str) -> str:
        """Clean license plate text"""
        if not text:
            return ""
        
        # Remove whitespace and special characters
        cleaned = re.sub(r'[^A-Z0-9]', '', text.upper())
        
        # Remove common OCR errors
        cleaned = cleaned.replace('O', '0')
        cleaned = cleaned.replace('I', '1')
        cleaned = cleaned.replace('S', '5')
        cleaned = cleaned.replace('B', '8')
        cleaned = cleaned.replace('G', '6')
        
        return cleaned
    
    def _detect_format(self, text: str, country: str = None) -> Tuple[PlateFormat, str, str]:
        """Detect license plate format and country"""
        if country and country in self.format_patterns:
            # Validate against specific country
            for format_name, pattern in self.format_patterns[country].items():
                if re.match(pattern, text):
                    return self._get_format_enum(format_name, country), country, format_name
        
        # Auto-detect format
        for country_code, patterns in self.format_patterns.items():
            for format_name, pattern in patterns.items():
                if re.match(pattern, text):
                    return self._get_format_enum(format_name, country_code), country_code, format_name
        
        return PlateFormat.UNKNOWN, "", ""
    
    def _get_format_enum(self, format_name: str, country: str) -> PlateFormat:
        """Convert format name to enum"""
        format_mapping = {
            "standard": PlateFormat.US_STANDARD if country == "US" else PlateFormat.UK_STANDARD if country == "UK" else PlateFormat.EU_STANDARD,
            "california": PlateFormat.US_CALIFORNIA,
            "new_york": PlateFormat.US_NEW_YORK,
        }
        
        return format_mapping.get(format_name, PlateFormat.UNKNOWN)
    
    def _validate_against_format(self, text: str, format_detected: PlateFormat, country: str) -> Tuple[bool, float, List[str]]:
        """Validate text against detected format"""
        if format_detected == PlateFormat.UNKNOWN:
            return False, 0.0, ["Unknown format"]
        
        # Get pattern for format
        pattern = self._get_pattern_for_format(format_detected, country)
        if not pattern:
            return False, 0.0, ["No pattern found"]
        
        # Check if text matches pattern
        if re.match(pattern, text):
            confidence = self._calculate_confidence(text, format_detected)
            suggestions = []
            return True, confidence, suggestions
        else:
            # Generate suggestions
            suggestions = self._generate_suggestions(text, format_detected)
            return False, 0.0, suggestions
    
    def _get_pattern_for_format(self, format_detected: PlateFormat, country: str) -> str:
        """Get regex pattern for format"""
        if country not in self.format_patterns:
            return None
        
        # Map format enum to pattern name
        format_mapping = {
            PlateFormat.US_STANDARD: "standard",
            PlateFormat.US_CALIFORNIA: "california",
            PlateFormat.US_NEW_YORK: "new_york",
            PlateFormat.UK_STANDARD: "standard",
            PlateFormat.EU_STANDARD: "standard"
        }
        
        pattern_name = format_mapping.get(format_detected, "standard")
        return self.format_patterns[country].get(pattern_name)
    
    def _calculate_confidence(self, text: str, format_detected: PlateFormat) -> float:
        """Calculate confidence score for validation"""
        base_confidence = 0.8
        
        # Adjust based on length
        if len(text) < 4 or len(text) > 8:
            base_confidence -= 0.2
        
        # Adjust based on character distribution
        alpha_count = sum(1 for c in text if c.isalpha())
        digit_count = sum(1 for c in text if c.isdigit())
        
        if alpha_count == 0 or digit_count == 0:
            base_confidence -= 0.3
        
        # Adjust based on format-specific rules
        if format_detected == PlateFormat.US_CALIFORNIA:
            if len(text) == 7 and text[0].isdigit():
                base_confidence += 0.1
        
        return max(0.0, min(1.0, base_confidence))
    
    def _generate_suggestions(self, text: str, format_detected: PlateFormat) -> List[str]:
        """Generate suggestions for invalid plates"""
        suggestions = []
        
        if len(text) < 4:
            suggestions.append("Plate too short - typical plates are 4-8 characters")
        elif len(text) > 8:
            suggestions.append("Plate too long - typical plates are 4-8 characters")
        
        if not any(c.isalpha() for c in text):
            suggestions.append("Plate should contain letters")
        
        if not any(c.isdigit() for c in text):
            suggestions.append("Plate should contain numbers")
        
        # Format-specific suggestions
        if format_detected == PlateFormat.US_CALIFORNIA:
            suggestions.append("California format: 1ABC123 (number + 3 letters + 3 numbers)")
        elif format_detected == PlateFormat.US_NEW_YORK:
            suggestions.append("New York format: ABC1234 (3 letters + 4 numbers)")
        elif format_detected == PlateFormat.UK_STANDARD:
            suggestions.append("UK format: AB12CDE (2 letters + 2 numbers + 3 letters)")
        
        return suggestions
    
    def get_performance_metrics(self) -> Dict:
        """Get performance metrics"""
        avg_processing_time = np.mean(self.validation_times) if self.validation_times else 0
        validation_rate = self.valid_plates / self.total_validations if self.total_validations > 0 else 0
        
        return {
            'total_validations': self.total_validations,
            'valid_plates': self.valid_plates,
            'invalid_plates': self.invalid_plates,
            'validation_rate': validation_rate,
            'avg_processing_time_ms': avg_processing_time * 1000,
            'max_processing_time_ms': max(self.validation_times) * 1000 if self.validation_times else 0,
            'supported_countries': self.supported_countries
        }

class PlateAnonymizer:
    """
    License plate anonymizer for privacy compliance
    Anonymizes plate data while preserving format for analysis
    """
    
    def __init__(self, anonymization_level: str = "partial"):
        """
        Initialize plate anonymizer
        
        Args:
            anonymization_level: Level of anonymization (full, partial, none)
        """
        self.anonymization_level = anonymization_level
        
        # Performance tracking
        self.anonymization_times = deque(maxlen=100)
        self.total_anonymizations = 0
        
        logger.info(f"Plate Anonymizer initialized: {anonymization_level}")
    
    def anonymize_plate(self, plate_text: str) -> str:
        """
        Anonymize license plate text
        
        Args:
            plate_text: Original plate text
        
        Returns:
            Anonymized plate text
        """
        if self.anonymization_level == "none":
            return plate_text
        
        start_time = time.time()
        
        if self.anonymization_level == "full":
            # Replace all characters with X
            anonymized = "X" * len(plate_text)
        elif self.anonymization_level == "partial":
            # Keep first and last character, replace middle with X
            if len(plate_text) <= 2:
                anonymized = "X" * len(plate_text)
            else:
                anonymized = plate_text[0] + "X" * (len(plate_text) - 2) + plate_text[-1]
        else:
            anonymized = plate_text
        
        # Update metrics
        processing_time = time.time() - start_time
        self.anonymization_times.append(processing_time)
        self.total_anonymizations += 1
        
        logger.debug(f"Plate anonymized: '{plate_text}' -> '{anonymized}' in {processing_time*1000:.2f}ms")
        
        return anonymized
    
    def get_performance_metrics(self) -> Dict:
        """Get performance metrics"""
        avg_processing_time = np.mean(self.anonymization_times) if self.anonymization_times else 0
        
        return {
            'total_anonymizations': self.total_anonymizations,
            'avg_processing_time_ms': avg_processing_time * 1000,
            'max_processing_time_ms': max(self.anonymization_times) * 1000 if self.anonymization_times else 0,
            'anonymization_level': self.anonymization_level
        }
