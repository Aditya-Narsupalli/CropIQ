# backend/app/api/endpoints/disease.py

import logging
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Form
from PIL import UnidentifiedImageError # Specific error if PIL can't open image

# Import AI service, config, and response model
import asyncio

from app.core.ai_services import get_disease_prediction
from app.services.disease_classifier import classify, model_crop
from app.services.kcc_archive import disease_references
from app.core.config import get_settings, Settings
from app.models.disease_model import DiseaseResponse

# --- Logging Setup ---
# Configure logging for this module
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Router Setup ---
router = APIRouter()

# --- Dependency for Validated Settings ---
# This checks settings on endpoint call and improves testability
async def get_validated_settings(settings: Settings = Depends(get_settings)) -> Settings:
    """Dependency to get settings and validate necessary API keys."""
    # Specific check for Gemini key needed by this endpoint's service
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == "YOUR_GEMINI_API_KEY_NOT_SET":
        logger.error("Gemini API Key is not configured in settings.")
        # Use 503 Service Unavailable as the dependency (AI service) isn't ready
        raise HTTPException(status_code=503, detail="AI Service (Gemini) is not configured correctly.")
    return settings

# --- API Endpoint ---
@router.post(
    "/detect",
    response_model=DiseaseResponse, # Use the Pydantic model for response structure
    status_code=200,
    summary="Detect Crop Disease from Image",
    description="Upload a plant image to get an AI-based analysis of potential diseases or pests. "
                "Supported formats include JPEG, PNG, WEBP etc.",
    tags=["Disease Detection"] # Consistent tagging for OpenAPI docs
)
async def detect_crop_disease(
    *, # Makes following arguments keyword-only, good practice
    settings: Settings = Depends(get_validated_settings), # Inject validated settings
    file: UploadFile = File(..., description="Image file of the plant."), # File is required
    crop_type: str = Form("crop", description="Type of crop (e.g., tomato, wheat, rice)"),
    location: str = Form("", description="Location of the farm"),
) -> DiseaseResponse:
    """
    Handles plant image uploads, validates them, sends for AI analysis,
    and returns the disease prediction results.

    Args:
        settings: Injected application settings.
        file: The uploaded image file.

    Returns:
        A DiseaseResponse object containing the analysis and filename.

    Raises:
        HTTPException: For various errors like invalid file type, size,
                       AI service errors, or internal server errors.
    """
    logger.info(f"Received request to detect disease for file: {file.filename}")

    # 1. Validate File Type (using content_type)
    if not file.content_type or not file.content_type.startswith("image/"):
        logger.warning(f"Invalid file type '{file.content_type}' for file '{file.filename}'.")
        raise HTTPException(
            status_code=400, # Bad Request
            detail=f"Invalid file type: '{file.content_type}'. Please upload a standard image format (JPEG, PNG, WEBP, etc.)."
        )

    # 2. Read File Content and Validate Size
    max_size_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    image_bytes = None
    try:
        # Read the file content into memory. For very large files (>50-100MB),
        # streaming would be better but more complex for API calls.
        # This approach is acceptable for typical image sizes with a limit.
        image_bytes = await file.read()

        if not image_bytes:
            logger.warning(f"Empty file uploaded: {file.filename}")
            raise HTTPException(status_code=400, detail="Received an empty image file. Please upload a valid image.")

        file_size = len(image_bytes)
        if file_size > max_size_bytes:
            logger.warning(f"File too large: {file_size} bytes for file '{file.filename}'. Limit is {max_size_bytes} bytes.")
            raise HTTPException(
                status_code=413, # Payload Too Large
                detail=f"File is too large ({round(file_size/(1024*1024), 2)} MB). Maximum size allowed is {settings.MAX_FILE_SIZE_MB}MB."
            )
        logger.info(f"File '{file.filename}' size validated ({round(file_size/(1024*1024), 2)} MB).")

    except Exception as e:
        # Catch potential errors during file reading
        logger.error(f"Error reading uploaded file '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Could not read uploaded file: {str(e)}")
    finally:
        # It's crucial to close the file handle
        await file.close()
        logger.debug(f"File '{file.filename}' closed.")

    # 3. Call AI Service for Analysis
    try:
        logger.info(f"Sending image '{file.filename}' to AI service...")
        # Call the asynchronous function from ai_services with context
        # Trained classifier first (crops it covers), then Gemini for the full
        # write-up, given the classifier's finding as evidence.
        try:
            finding = await asyncio.to_thread(classify, image_bytes, crop_type)
        except Exception as e:
            logger.warning(f"Disease classifier failed, continuing with Gemini only: {e}")
            finding = None
        # Real expert answers from the Kisan Call Centre archive for the
        # disease the model found - grounds the treatment advice.
        references = []
        if finding and finding["confident"]:
            references = await asyncio.to_thread(disease_references, finding["crop"], finding["disease"])
        prediction_result = await get_disease_prediction(
            image_bytes, crop_type, location, model_finding=finding, references=references,
        )
        logger.info(f"Received AI analysis successfully for '{file.filename}'.")

        gemini_failed = prediction_result.startswith("Error")

        # Crops the trained model doesn't cover: look up the disease Gemini
        # identified, so every crop gets Kisan Call Centre expert answers.
        if not references and not gemini_failed:
            identified = _identification(prediction_result)
            if identified:
                references = await asyncio.to_thread(
                    disease_references, model_crop(crop_type) or crop_type.strip().title(), identified,
                )
        if gemini_failed and not finding:
            logger.error(f"AI Service returned an error message for '{file.filename}': {prediction_result}")
            # Propagate the error from the service, indicating the service had an issue
            # Don't show the farmer the provider's raw error text (quota details etc.)
            raise HTTPException(
                status_code=503,
                detail="Photo analysis is temporarily unavailable (the AI service is busy or has reached its "
                       "daily limit). Please try again later.",
            )
        if gemini_failed:
            # Gemini down (e.g. quota) - the trained model's answer still stands
            prediction_result = _model_only_analysis(finding)

        # 4. Return Successful Response using the Pydantic model
        return DiseaseResponse(
            analysis=prediction_result,
            filename=file.filename or "unknown_filename", # Provide a default if filename is None
            model_finding=finding,
            kcc_references=references,
            source=("model" if gemini_failed else "model+gemini") if finding else "gemini",
        )

    except UnidentifiedImageError:
        # Specific error if PIL (likely used in ai_services) cannot identify the image
        logger.warning(f"Cannot identify image format for file '{file.filename}'. It might be corrupt or unsupported.")
        raise HTTPException(status_code=400, detail="Could not identify image format. Please ensure it's a standard, non-corrupted image.")
    except HTTPException as http_exc:
        # Re-raise exceptions that are already HTTPException (like the 503 above)
        raise http_exc
    except Exception as e:
        # Catch any other unexpected errors during the AI call or processing
        # Log the full traceback for debugging
        logger.error(f"Unexpected error during AI analysis for '{file.filename}': {e}", exc_info=True)
        # Return a generic 500 Internal Server Error to the client
        raise HTTPException(
            status_code=500, # Internal Server Error
            detail="An internal server error occurred while analyzing the image. Please try again later."
        )

def _model_only_analysis(finding: dict) -> str:
    """Plain-text result when only the trained classifier is available."""
    lines = [f"Likely: {finding['disease']} on {finding['crop']} ({finding['confidence']:.0%} probability)."]
    if not finding["confident"]:
        lines.append("The model isn't confident about this photo - try a clearer, close-up photo of one "
                     "affected leaf in daylight.")
    others = [f"{t['disease']} ({t['probability']:.0%})" for t in finding["top_predictions"][1:]]
    if others:
        lines.append("Other possibilities: " + ", ".join(others) + ".")
    lines.append("Detailed treatment advice is temporarily unavailable - see the Kisan Call Centre expert "
                 "answers below if shown. Confirm the diagnosis and treatment with your local Krishi Vigyan "
                 "Kendra or agriculture officer before spraying.")
    return "\n".join(lines)


def _identification(analysis: str):
    """The disease named on Gemini's 'IDENTIFICATION: ...' first line, if any."""
    for line in analysis.splitlines()[:5]:
        cleaned = line.strip().strip("*#").strip()
        if cleaned.upper().startswith("IDENTIFICATION:"):
            name = cleaned.split(":", 1)[1].strip().strip("*").strip()
            return None if name.lower() in ("healthy", "unclear", "") else name
    return None
