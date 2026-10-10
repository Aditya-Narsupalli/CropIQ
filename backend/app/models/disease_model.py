# backend/app/models/disease_model.py
from typing import List, Optional

from pydantic import BaseModel, Field


class DiseasePrediction(BaseModel):
    disease: str
    probability: float


class ModelFinding(BaseModel):
    """Result of CropIQ's trained classifier (app/services/disease_classifier.py)."""
    crop: str
    disease: str
    confidence: float
    confident: bool
    top_predictions: List[DiseasePrediction]
    model_accuracy: Optional[float] = None
    possible_diseases: List[str] = []


class KccReference(BaseModel):
    """A past Kisan Call Centre question and expert answer about this disease."""
    question: str
    answer: str
    crop: Optional[str] = None
    score: float


class DiseaseResponse(BaseModel):
    analysis: str = Field(..., description="The text analysis result from the AI model regarding potential diseases or pests.")
    filename: str = Field(..., description="The original filename of the uploaded image.")
    # Trained classifier result - None when the crop isn't covered by the model
    model_finding: Optional[ModelFinding] = None
    # Expert answers from India's Kisan Call Centre archive for the identified disease
    kcc_references: List[KccReference] = []
    # "model+gemini", "model" (Gemini unavailable) or "gemini" (crop not covered)
    source: str = "gemini"

    class Config:
        # Example for OpenAPI documentation generation
        schema_extra =  {
            "example": {
                "analysis": "The image shows signs of Powdery Mildew. Symptoms include white, powdery spots on leaves. Suggested management: Improve air circulation and consider using approved fungicides.",
                "filename": "plant_image_01.jpg"
            }
        }