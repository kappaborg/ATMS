#!/usr/bin/env python3
"""
Convert YOLOv8 Model to CoreML Format
Optimizes for Apple Silicon (M1/M2/M3) - 3-5× faster inference
"""
import sys
from pathlib import Path

# Add project paths
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "services" / "ai-perception" / "src"))

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    print("❌ Ultralytics YOLO not available. Install: pip install ultralytics")
    sys.exit(1)

try:
    import coremltools as ct
    COREML_AVAILABLE = True
except ImportError:
    print("❌ CoreML Tools not available. Install: pip install coremltools")
    sys.exit(1)

import torch


def convert_yolo_to_coreml(
    model_path: str,
    output_path: str = None,
    input_shape: tuple = (640, 640),
    compute_units: str = "ALL"  # "ALL", "CPU_AND_NE", "CPU_ONLY"
):
    """
    Convert YOLOv8 PyTorch model to CoreML format
    
    Args:
        model_path: Path to .pt YOLOv8 model
        output_path: Output path for .mlpackage (default: same as input with .mlpackage extension)
        input_shape: Input image shape (width, height)
        compute_units: CoreML compute units ("ALL" uses Neural Engine + GPU + CPU)
    
    Returns:
        Path to converted model
    """
    model_path = Path(model_path)
    
    if not model_path.exists():
        print(f"❌ Model not found: {model_path}")
        return None
    
    if output_path is None:
        output_path = model_path.with_suffix('.mlpackage')
    else:
        output_path = Path(output_path)
    
    print(f"🔄 Converting {model_path.name} to CoreML format...")
    print(f"   Input: {model_path}")
    print(f"   Output: {output_path}")
    print(f"   Input shape: {input_shape}")
    print(f"   Compute units: {compute_units}")
    
    try:
        # Load YOLOv8 model
        print("\n📦 Loading YOLOv8 model...")
        model = YOLO(str(model_path))
        
        # Export to CoreML
        print("🔄 Exporting to CoreML...")
        # YOLOv8 has built-in export method
        exported_path = model.export(
            format='coreml',
            imgsz=input_shape,
            simplify=True,
            opset=12,
            nms=True  # Include NMS in model
        )
        
        # Move to desired output path if different
        exported_path = Path(exported_path)
        if exported_path != output_path:
            import shutil
            if output_path.exists():
                shutil.rmtree(output_path)
            shutil.move(str(exported_path), str(output_path))
        
        print(f"✅ CoreML model saved: {output_path}")
        
        # Verify the model
        print("\n🔍 Verifying CoreML model...")
        try:
            mlmodel = ct.models.MLModel(str(output_path))
            print(f"   ✅ Model loaded successfully")
            print(f"   📊 Model type: {mlmodel.model_type}")
            print(f"   📝 Description: {mlmodel.description}")
            
            # Check input/output specs
            if hasattr(mlmodel, 'spec') and hasattr(mlmodel.spec, 'description'):
                print(f"   📥 Inputs: {len(mlmodel.spec.description.input)}")
                print(f"   📤 Outputs: {len(mlmodel.spec.description.output)}")
            
        except Exception as e:
            print(f"   ⚠️  Verification warning: {e}")
        
        print(f"\n✅ Conversion complete!")
        print(f"   Use this model path in your config: {output_path}")
        print(f"   Expected speedup: 3-5× faster on Apple Silicon")
        
        return output_path
        
    except Exception as e:
        print(f"❌ Conversion failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Main conversion function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Convert YOLOv8 model to CoreML format")
    parser.add_argument(
        'model_path',
        type=str,
        help='Path to YOLOv8 .pt model file'
    )
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Output path for .mlpackage (default: same as input with .mlpackage extension)'
    )
    parser.add_argument(
        '--input-shape',
        type=int,
        nargs=2,
        default=[640, 640],
        metavar=('WIDTH', 'HEIGHT'),
        help='Input image shape (default: 640 640)'
    )
    parser.add_argument(
        '--compute-units',
        type=str,
        default='ALL',
        choices=['ALL', 'CPU_AND_NE', 'CPU_ONLY'],
        help='CoreML compute units (default: ALL - uses Neural Engine + GPU + CPU)'
    )
    
    args = parser.parse_args()
    
    # Convert model
    result = convert_yolo_to_coreml(
        model_path=args.model_path,
        output_path=args.output,
        input_shape=tuple(args.input_shape),
        compute_units=args.compute_units
    )
    
    if result:
        print(f"\n🎉 Success! Model converted to: {result}")
        print(f"\n💡 Next steps:")
        print(f"   1. Update model config to use: {result}")
        print(f"   2. Restart AI Perception service")
        print(f"   3. CoreML will be used automatically (3-5× faster!)")
        sys.exit(0)
    else:
        print("\n❌ Conversion failed")
        sys.exit(1)


if __name__ == "__main__":
    main()

