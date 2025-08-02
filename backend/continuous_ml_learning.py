#!/usr/bin/env python3
"""
Continuous ML Learning System
Handles incremental model training and intelligent data processing
"""
import os
import pickle
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
import joblib
import asyncio

logger = logging.getLogger(__name__)

class ContinuousMLLearningSystem:
    """
    Intelligent ML system that:
    1. Detects when users log in
    2. Checks if sufficient new data exists
    3. Performs incremental training on new data
    4. Updates predictions and insights
    """
    
    def __init__(self):
        self.models_dir = "ml_models"
        self.min_training_samples = 50  # Minimum new samples to trigger retraining
        self.retrain_interval_days = 7  # Minimum days between retraining
        self.model_versions = {}  # Track model versions per user
        
        # Ensure models directory exists
        os.makedirs(self.models_dir, exist_ok=True)
        
    def get_user_model_path(self, user_email: str, model_type: str) -> str:
        """Get file path for user's specific model"""
        safe_email = user_email.replace('@', '_at_').replace('.', '_dot_')
        return os.path.join(self.models_dir, f"{safe_email}_{model_type}.pkl")
    
    def get_user_scaler_path(self, user_email: str) -> str:
        """Get file path for user's data scaler"""
        safe_email = user_email.replace('@', '_at_').replace('.', '_dot_')
        return os.path.join(self.models_dir, f"{safe_email}_scaler.pkl")
    
    def load_user_model(self, user_email: str, model_type: str = "productivity"):
        """Load user's personalized model if it exists"""
        model_path = self.get_user_model_path(user_email, model_type)
        scaler_path = self.get_user_scaler_path(user_email)
        
        try:
            if os.path.exists(model_path) and os.path.exists(scaler_path):
                model = joblib.load(model_path)
                scaler = joblib.load(scaler_path)
                
                # Load model metadata
                metadata_path = model_path.replace('.pkl', '_metadata.pkl')
                metadata = {}
                if os.path.exists(metadata_path):
                    with open(metadata_path, 'rb') as f:
                        metadata = pickle.load(f)
                
                logger.info(f"✅ Loaded personalized model for {user_email}")
                return model, scaler, metadata
            else:
                logger.info(f"🆕 No existing model found for {user_email}, will create new one")
                return None, None, {}
        except Exception as e:
            logger.error(f"❌ Failed to load model for {user_email}: {e}")
            return None, None, {}
    
    def save_user_model(self, user_email: str, model, scaler, metadata: Dict, model_type: str = "productivity"):
        """Save user's personalized model"""
        try:
            model_path = self.get_user_model_path(user_email, model_type)
            scaler_path = self.get_user_scaler_path(user_email)
            metadata_path = model_path.replace('.pkl', '_metadata.pkl')
            
            # Update metadata
            metadata.update({
                'last_trained': datetime.now().isoformat(),
                'model_version': metadata.get('model_version', 0) + 1,
                'user_email': user_email
            })
            
            # Save model components
            joblib.dump(model, model_path)
            joblib.dump(scaler, scaler_path)
            
            with open(metadata_path, 'wb') as f:
                pickle.dump(metadata, f)
            
            logger.info(f"✅ Saved personalized model for {user_email} (version {metadata['model_version']})")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to save model for {user_email}: {e}")
            return False
    
    def check_training_requirements(self, user_email: str, db) -> Tuple[bool, Dict]:
        """
        Check if user needs model retraining based on:
        1. Amount of new data since last training
        2. Time since last training
        3. Data quality and completeness
        """
        try:
            # Get user's model metadata
            _, _, metadata = self.load_user_model(user_email)
            
            last_trained = metadata.get('last_trained')
            last_training_data_count = metadata.get('training_data_count', 0)
            
            # Get current data count
            user_metrics_history = db.get_user_metrics_history(user_email, limit=1000)
            current_data_count = len(user_metrics_history)
            
            # Calculate new data since last training
            new_data_count = current_data_count - last_training_data_count
            
            # Check time since last training
            days_since_training = float('inf')
            if last_trained:
                try:
                    last_trained_date = datetime.fromisoformat(last_trained)
                    days_since_training = (datetime.now() - last_trained_date).days
                except Exception:
                    days_since_training = float('inf')
            
            # Determine if retraining is needed
            needs_training = (
                new_data_count >= self.min_training_samples or  # Sufficient new data
                days_since_training >= self.retrain_interval_days or  # Time-based retraining
                not metadata  # First time training
            )
            
            training_info = {
                'needs_training': needs_training,
                'new_data_count': new_data_count,
                'days_since_training': days_since_training,
                'current_data_count': current_data_count,
                'last_trained': last_trained,
                'model_version': metadata.get('model_version', 0)
            }
            
            if needs_training:
                logger.info(f"🧠 User {user_email} needs model retraining: {new_data_count} new samples, {days_since_training} days since last training")
            else:
                logger.info(f"✅ User {user_email} model is up to date")
            
            return needs_training, training_info
            
        except Exception as e:
            logger.error(f"❌ Failed to check training requirements for {user_email}: {e}")
            return False, {"error": str(e)}
    
    def prepare_training_data(self, user_metrics_history: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Prepare user's historical data for ML training
        Extract features and target variables for productivity prediction
        """
        try:
            if len(user_metrics_history) < 10:
                raise ValueError("Insufficient data for training (minimum 10 records needed)")
            
            features = []
            targets = []
            
            for record in user_metrics_history:
                metrics = record.get('metrics_data', {})
                if not metrics:
                    continue
                
                # Extract feature vector
                feature_vector = [
                    metrics.get('total_commits', 0),
                    metrics.get('total_prs', 0),
                    metrics.get('lines_added', 0),
                    metrics.get('lines_deleted', 0),
                    metrics.get('files_changed', 0),
                    metrics.get('review_comments', 0),
                    metrics.get('dora', {}).get('lead_time', {}).get('total_lead_time_hours', 0),
                    metrics.get('dora', {}).get('deployment_frequency', {}).get('deployments_per_week', 0),
                    metrics.get('activity_score', 0),
                    metrics.get('collaboration_score', 0),
                    metrics.get('code_quality_score', 0),
                    len(metrics.get('languages', [])),
                    metrics.get('avg_commit_size', 0),
                    metrics.get('pr_success_rate', 0),
                ]
                
                # Target variable: overall performance score
                performance_score = metrics.get('performance_score', 
                    (metrics.get('activity_score', 0) + 
                     metrics.get('collaboration_score', 0) + 
                     metrics.get('code_quality_score', 0)) / 3
                )
                
                if len(feature_vector) == 14 and performance_score > 0:  # Valid data point
                    features.append(feature_vector)
                    targets.append(performance_score)
            
            if len(features) < 10:
                raise ValueError(f"After preprocessing, only {len(features)} valid samples remain (minimum 10 needed)")
            
            X = np.array(features)
            y = np.array(targets)
            
            logger.info(f"✅ Prepared training data: {X.shape[0]} samples, {X.shape[1]} features")
            return X, y
            
        except Exception as e:
            logger.error(f"❌ Failed to prepare training data: {e}")
            raise
    
    async def train_user_model(self, user_email: str, db) -> Dict:
        """
        Train/retrain user's personalized ML model
        """
        try:
            logger.info(f"🧠 Starting ML training for {user_email}")
            
            # Get user's historical data
            user_metrics_history = db.get_user_metrics_history(user_email, limit=1000)
            
            if len(user_metrics_history) < self.min_training_samples:
                return {
                    "success": False,
                    "error": f"Insufficient data: {len(user_metrics_history)} samples (minimum {self.min_training_samples})"
                }
            
            # Prepare training data
            X, y = self.prepare_training_data(user_metrics_history)
            
            # Load existing model or create new one
            existing_model, existing_scaler, metadata = self.load_user_model(user_email)
            
            # Initialize or update scaler
            if existing_scaler is None:
                scaler = StandardScaler()
                X_scaled = scaler.fit_transform(X)
                logger.info("🔧 Created new data scaler")
            else:
                # Incremental scaling update (partial_fit for new data)
                scaler = existing_scaler
                X_scaled = scaler.transform(X)
                logger.info("🔧 Using existing data scaler")
            
            # Split data for training/validation
            X_train, X_test, y_train, y_test = train_test_split(
                X_scaled, y, test_size=0.2, random_state=42
            )
            
            # Initialize or update model
            if existing_model is None:
                model = RandomForestRegressor(
                    n_estimators=100,
                    random_state=42,
                    n_jobs=-1
                )
                logger.info("🌟 Created new Random Forest model")
            else:
                # For incremental learning, retrain with all data
                model = RandomForestRegressor(
                    n_estimators=100,
                    random_state=42,
                    n_jobs=-1
                )
                logger.info("🔄 Retraining existing model with updated data")
            
            # Train the model
            model.fit(X_train, y_train)
            
            # Evaluate model performance
            train_score = model.score(X_train, y_train)
            test_score = model.score(X_test, y_test)
            
            # Update metadata
            training_metadata = {
                'training_data_count': len(user_metrics_history),
                'training_samples': X.shape[0],
                'features_count': X.shape[1],
                'train_score': train_score,
                'test_score': test_score,
                'feature_importance': model.feature_importances_.tolist(),
                'training_duration': datetime.now().isoformat()
            }
            metadata.update(training_metadata)
            
            # Save the trained model
            save_success = self.save_user_model(user_email, model, scaler, metadata)
            
            if save_success:
                logger.info(f"✅ ML training completed for {user_email}: Train R²={train_score:.3f}, Test R²={test_score:.3f}")
                
                return {
                    "success": True,
                    "train_score": train_score,
                    "test_score": test_score,
                    "samples_trained": X.shape[0],
                    "model_version": metadata['model_version']
                }
            else:
                return {"success": False, "error": "Failed to save trained model"}
            
        except Exception as e:
            logger.error(f"❌ ML training failed for {user_email}: {e}")
            return {"success": False, "error": str(e)}
    
    def generate_personalized_insights(self, user_email: str, current_metrics: Dict) -> Dict:
        """
        Generate personalized insights using the user's trained model
        """
        try:
            # Load user's personalized model
            model, scaler, metadata = self.load_user_model(user_email)
            
            if model is None:
                return {
                    "insights": ["No personalized model available yet. More data is being collected to provide personalized insights."],
                    "predictions": {},
                    "model_status": "not_trained"
                }
            
            # Prepare current metrics as feature vector
            feature_vector = np.array([[
                current_metrics.get('total_commits', 0),
                current_metrics.get('total_prs', 0),
                current_metrics.get('lines_added', 0),
                current_metrics.get('lines_deleted', 0),
                current_metrics.get('files_changed', 0),
                current_metrics.get('review_comments', 0),
                current_metrics.get('dora', {}).get('lead_time', {}).get('total_lead_time_hours', 0),
                current_metrics.get('dora', {}).get('deployment_frequency', {}).get('deployments_per_week', 0),
                current_metrics.get('activity_score', 0),
                current_metrics.get('collaboration_score', 0),
                current_metrics.get('code_quality_score', 0),
                len(current_metrics.get('languages', [])),
                current_metrics.get('avg_commit_size', 0),
                current_metrics.get('pr_success_rate', 0),
            ]])
            
            # Scale features
            feature_vector_scaled = scaler.transform(feature_vector)
            
            # Make prediction
            predicted_performance = model.predict(feature_vector_scaled)[0]
            
            # Get feature importance for insights
            feature_names = [
                'commits', 'prs', 'lines_added', 'lines_deleted', 'files_changed',
                'review_comments', 'lead_time', 'deployment_freq', 'activity_score',
                'collaboration_score', 'code_quality_score', 'languages', 'commit_size', 'pr_success_rate'
            ]
            
            feature_importance = metadata.get('feature_importance', [])
            
            # Generate personalized insights based on model
            insights = []
            
            if len(feature_importance) == len(feature_names):
                # Find top 3 most important features for this user
                importance_pairs = list(zip(feature_names, feature_importance))
                top_features = sorted(importance_pairs, key=lambda x: x[1], reverse=True)[:3]
                
                insights.append(f"Based on your personal coding patterns, your top performance drivers are: {', '.join([f[0] for f in top_features])}")
                
                # Compare current performance to prediction
                current_performance = current_metrics.get('performance_score', 0)
                if predicted_performance > current_performance:
                    insights.append(f"Your model predicts you could achieve {predicted_performance:.1f}% performance. Consider focusing on your key drivers.")
                elif predicted_performance < current_performance:
                    insights.append(f"You're performing above your typical pattern! Current: {current_performance:.1f}%, Predicted: {predicted_performance:.1f}%")
            
            # Add model-specific insights
            train_score = metadata.get('train_score', 0)
            if train_score > 0.8:
                insights.append(f"Your personalized model has high accuracy ({train_score:.1%}), providing reliable recommendations.")
            
            return {
                "insights": insights,
                "predictions": {
                    "expected_performance": predicted_performance,
                    "model_confidence": train_score
                },
                "model_status": "trained",
                "model_version": metadata.get('model_version', 1),
                "last_trained": metadata.get('last_trained')
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to generate personalized insights for {user_email}: {e}")
            return {
                "insights": ["Unable to generate personalized insights at this time."],
                "predictions": {},
                "model_status": "error",
                "error": str(e)
            }
    
    async def handle_user_login(self, user_email: str, db) -> Dict:
        """
        Handle ML processes when user logs in:
        1. Check if retraining is needed
        2. Train model if necessary
        3. Generate updated insights
        """
        try:
            logger.info(f"🧠 Processing ML for user login: {user_email}")
            
            # Check if model needs retraining
            needs_training, training_info = self.check_training_requirements(user_email, db)
            
            ml_status = {
                "user_email": user_email,
                "training_info": training_info,
                "training_triggered": False,
                "insights_updated": False
            }
            
            # Perform training if needed
            if needs_training:
                logger.info(f"🔄 Triggering ML retraining for {user_email}")
                training_result = await self.train_user_model(user_email, db)
                ml_status["training_result"] = training_result
                ml_status["training_triggered"] = True
                
                if training_result.get("success"):
                    logger.info(f"✅ ML retraining completed successfully for {user_email}")
                else:
                    logger.warning(f"⚠️ ML retraining failed for {user_email}: {training_result.get('error')}")
            else:
                logger.info(f"⏭️ No ML retraining needed for {user_email}")
            
            # Generate fresh insights regardless of training
            current_metrics = db.get_latest_user_metrics(user_email)
            if current_metrics:
                insights = self.generate_personalized_insights(user_email, current_metrics)
                ml_status["insights"] = insights
                ml_status["insights_updated"] = True
            
            return ml_status
            
        except Exception as e:
            logger.error(f"❌ ML processing failed for user login {user_email}: {e}")
            return {
                "user_email": user_email,
                "error": str(e),
                "training_triggered": False,
                "insights_updated": False
            }

# Global instance
ml_learning_system = ContinuousMLLearningSystem()

async def process_user_ml_on_login(user_email: str, db) -> Dict:
    """
    Main function to call when user logs in
    Handles all ML-related processing
    """
    return await ml_learning_system.handle_user_login(user_email, db)

def get_personalized_insights(user_email: str, current_metrics: Dict) -> Dict:
    """
    Get personalized insights for user (synchronous version)
    """
    return ml_learning_system.generate_personalized_insights(user_email, current_metrics)
