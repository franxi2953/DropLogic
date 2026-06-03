# Models Directory

This directory should contain the trained YOLO11 model file for droplet detection.

## Required Files

- `best.pt` - Your trained YOLO11 model file (.pt format)

## How to Obtain the Model

### Option 1: Train Your Own Model
Follow the training guide in `YOLO_Training/droplet_training_guide.md` to train a custom model for your specific droplet detection needs.

### Option 2: Use Pre-trained Model
If you have a pre-trained model, copy it here and rename it to `best.pt`.

### Option 3: Download from Repository
If a pre-trained model is available in your project repository, download and place it here.

## Model Requirements

- **Format**: PyTorch (.pt) file from YOLO11 training
- **Classes**: Should include at least 'droplet' class
- **Input Size**: Trained on 640x640 or 1280x1280 images
- **Framework**: Compatible with ultralytics YOLO library

## Testing the Model

Once you have placed `best.pt` here, you can test it using:

```bash
cd DropLogic library
python -m droplogic.utils.drop_vision.test_detector
```

## Troubleshooting

If the model fails to load:
1. Ensure the file is named exactly `best.pt`
2. Verify it's a valid YOLO11 PyTorch model
3. Check that `ultralytics` package is installed
4. Ensure the model was trained with compatible YOLO version