import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge, SGDRegressor
from sklearn.ensemble import IsolationForest, RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import mean_absolute_error, r2_score, mean_squared_error
from datetime import datetime, timedelta, date
import logging
from typing import Dict, List, Any, Tuple, Optional
import warnings
import pickle
import os

try:
    from statsmodels.tsa.arima.model import ARIMA
    import pmdarima as pm
    ARIMA_AVAILABLE = True
except ImportError:
    ARIMA_AVAILABLE = False

warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)

class EnhancedMLAnalyzer:
    """Advanced ML analyzer with continuous learning capabilities and performance tracking."""
    
    # Class-level constants for thresholds and continuous learning
    MIN_FORECAST_POINTS = 10
    MIN_CLUSTER_USERS = 3
    ANOMALY_Z_THRESHOLD = 2.5
    ANOMALY_IFOREST_CONTAM = 0.1
    MOVING_AVG_WINDOW = 7
    CONTINUOUS_LEARNING_THRESHOLD = 5  # Minimum new points to trigger incremental learning
    MODEL_SAVE_PATH = "ml_models"  # Directory to save/load models
    LEARNING_RATE = 0.01  # For SGD models
    MAX_MODEL_AGE_DAYS = 30  # Retrain full model if older than this
    
    def __init__(self):
        self.scalers = {}
        self.models = {}
        self.anomaly_detectors = {}
        self.trend_analyzers = {}
        self.model_metadata = {}  # Track training history, performance, etc.
        self.performance_history = {}  # Track model performance over time
        self.last_training_data = {}  # Cache last training data for incremental updates
        
        # Ensure model save directory exists
        if not os.path.exists(self.MODEL_SAVE_PATH):
            os.makedirs(self.MODEL_SAVE_PATH)
            
        # Load existing models if available
        self._load_existing_models()
        
    def _load_existing_models(self):
        """Load previously trained models from disk for continuous learning."""
        try:
            model_files = [f for f in os.listdir(self.MODEL_SAVE_PATH) if f.endswith('.pkl')]
            for model_file in model_files:
                metric_name = model_file.replace('.pkl', '')
                model_path = os.path.join(self.MODEL_SAVE_PATH, model_file)
                
                try:
                    with open(model_path, 'rb') as f:
                        model_data = pickle.load(f)
                        self.models[metric_name] = model_data.get('model')
                        self.model_metadata[metric_name] = model_data.get('metadata', {})
                        self.scalers[metric_name] = model_data.get('scaler')
                        self.last_training_data[metric_name] = model_data.get('last_data', {})
                        
                    logger.info(f"Loaded existing model for {metric_name}")
                except Exception as e:
                    logger.warning(f"Failed to load model for {metric_name}: {e}")
        except Exception as e:
            logger.warning(f"Failed to load existing models: {e}")
    
    def _save_model(self, metric_name: str):
        """Save trained model to disk for persistence."""
        try:
            model_path = os.path.join(self.MODEL_SAVE_PATH, f"{metric_name}.pkl")
            model_data = {
                'model': self.models.get(metric_name),
                'metadata': self.model_metadata.get(metric_name, {}),
                'scaler': self.scalers.get(metric_name),
                'last_data': self.last_training_data.get(metric_name, {}),
                'saved_at': datetime.now().isoformat()
            }
            
            with open(model_path, 'wb') as f:
                pickle.dump(model_data, f)
                
            logger.info(f"Saved model for {metric_name}")
        except Exception as e:
            logger.error(f"Failed to save model for {metric_name}: {e}")
    
    def _should_retrain_full_model(self, metric_name: str) -> bool:
        """Determine if we should do full retraining vs incremental learning."""
        metadata = self.model_metadata.get(metric_name, {})
        last_full_training = metadata.get('last_full_training')
        
        if not last_full_training:
            return True
            
        try:
            last_training_date = datetime.fromisoformat(last_full_training)
            days_since_training = (datetime.now() - last_training_date).days
            return days_since_training > self.MAX_MODEL_AGE_DAYS
        except:
            return True
    
    def _detect_new_data_points(self, historical_data: List[Dict], metric_name: str) -> List[Dict]:
        """Detect new data points since last training for incremental learning."""
        last_data = self.last_training_data.get(metric_name, {})
        last_timestamp = last_data.get('last_timestamp')
        
        if not last_timestamp:
            return historical_data  # All data is new
            
        try:
            last_time = datetime.fromisoformat(last_timestamp)
            new_data = [
                entry for entry in historical_data
                if datetime.fromisoformat(entry['metric_timestamp'].replace('Z', '+00:00')) > last_time
            ]
            return new_data
        except Exception as e:
            logger.warning(f"Failed to detect new data points for {metric_name}: {e}")
            return historical_data
        
    def prepare_time_series_data(self, historical_data: List[Dict], metric_name: str) -> Tuple[np.ndarray, np.ndarray, List[datetime]]:
        """Prepare time series data for ML analysis."""
        if not historical_data:
            return np.array([]), np.array([]), []
            
        # Sort by timestamp (try metric_timestamp first, then date)
        def get_sort_key(x):
            timestamp = x.get('metric_timestamp') or x.get('date') or x.get('created_at', '1970-01-01')
            if isinstance(timestamp, str):
                return timestamp
            return timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp)
            
        sorted_data = sorted(historical_data, key=get_sort_key)
        timestamps = []
        values = []
        
        for entry in sorted_data:
            try:
                # Try metric_timestamp first, fallback to date field
                timestamp_str = entry.get('metric_timestamp') or entry.get('date')
                if not timestamp_str:
                    continue
                    
                # Handle different timestamp formats
                if isinstance(timestamp_str, str):
                    try:
                        # Try parsing as full datetime first
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    except ValueError:
                        try:
                            # If that fails, try adding T00:00:00 for date-only strings
                            timestamp = datetime.fromisoformat(timestamp_str + 'T00:00:00')
                        except ValueError:
                            # Skip this entry if we can't parse it
                            logger.warning(f"Failed to parse timestamp: {timestamp_str}")
                            continue
                elif isinstance(timestamp_str, datetime):
                    # Already a datetime object
                    timestamp = timestamp_str
                elif isinstance(timestamp_str, date):
                    # Date object, convert to datetime
                    timestamp = datetime.combine(timestamp_str, datetime.min.time())
                else:
                    # Try to convert string representation
                    try:
                        timestamp = datetime.fromisoformat(str(timestamp_str).replace('Z', '+00:00'))
                    except ValueError:
                        logger.warning(f"Failed to parse timestamp: {timestamp_str}")
                        continue
                
                # Try to extract from metrics_data first, then fall back to direct field access
                metric_value = self._extract_nested_metric(entry.get('metrics_data', {}), metric_name)
                if metric_value is None:
                    # Try direct field access
                    metric_value = entry.get(metric_name)
                
                if metric_value is not None:
                    timestamps.append(timestamp)
                    values.append(metric_value)
            except Exception as e:
                logger.warning(f"Failed to parse entry: {e}")
                continue
                
        if not timestamps:
            return np.array([]), np.array([]), []
            
        # Create features (days since first timestamp)
        base_time = timestamps[0]
        
        # Ensure base_time is datetime for proper arithmetic
        if isinstance(base_time, date) and not isinstance(base_time, datetime):
            base_time = datetime.combine(base_time, datetime.min.time())
            
        # Convert all timestamps to datetime for consistent arithmetic
        datetime_timestamps = []
        for ts in timestamps:
            if isinstance(ts, datetime):
                datetime_timestamps.append(ts)
            elif isinstance(ts, date):
                datetime_timestamps.append(datetime.combine(ts, datetime.min.time()))
            else:
                datetime_timestamps.append(ts)
                
        X = np.array([(ts - base_time).days for ts in datetime_timestamps]).reshape(-1, 1)
        y = np.array(values)
        
        return X, y, timestamps
        
    def train_forecasting_model(self, historical_data: List[Dict], metric_name: str):
        """Train or update forecasting model with continuous learning capabilities."""
        try:
            # Check if we have enough data
            if len(historical_data) < self.MIN_FORECAST_POINTS:
                logger.warning(f"Insufficient data for forecasting model training: {len(historical_data)} < {self.MIN_FORECAST_POINTS}")
                return False
            
            # Detect new data points
            new_data = self._detect_new_data_points(historical_data, metric_name)
            has_new_data = len(new_data) >= self.CONTINUOUS_LEARNING_THRESHOLD
            
            # Decide on training strategy
            should_full_retrain = self._should_retrain_full_model(metric_name)
            has_existing_model = metric_name in self.models
            
            if should_full_retrain or not has_existing_model:
                logger.info(f"Full retraining for {metric_name} (new model: {not has_existing_model}, age-based: {should_full_retrain})")
                return self._train_full_model(historical_data, metric_name)
            elif has_new_data:
                logger.info(f"Incremental learning for {metric_name} with {len(new_data)} new data points")
                return self._update_model_incrementally(new_data, historical_data, metric_name)
            else:
                logger.info(f"No significant new data for {metric_name}, using existing model")
                return True
                
        except Exception as e:
            logger.error(f"Model training/updating failed for {metric_name}: {str(e)}")
            return False
    
    def _train_full_model(self, historical_data: List[Dict], metric_name: str):
        """Train a new model from scratch with all available data."""
        try:
            X, y, timestamps = self.prepare_time_series_data(historical_data, metric_name)
            
            if len(y) < self.MIN_FORECAST_POINTS:
                return False
            
            # Initialize metadata
            self.model_metadata[metric_name] = {
                'last_full_training': datetime.now().isoformat(),
                'training_data_points': len(y),
                'model_version': 1,
                'performance_history': []
            }
            
            # Prepare features and scaling
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            self.scalers[metric_name] = scaler
            
            # Try ARIMA first, fallback to continuous learning models
            model_trained = False
            
            if ARIMA_AVAILABLE and len(y) >= 10:
                try:
                    model = pm.auto_arima(y, seasonal=True, m=4, suppress_warnings=True, error_action='ignore')
                    self.models[metric_name] = {
                        'type': 'arima',
                        'model': model,
                        'supports_incremental': False
                    }
                    model_trained = True
                    logger.info(f"Trained ARIMA model for {metric_name}")
                except Exception as e:
                    logger.warning(f"ARIMA training failed for {metric_name}: {e}")
            
            # If ARIMA failed or not available, use SGD for continuous learning
            if not model_trained:
                # Use SGDRegressor for continuous learning capability
                sgd_model = SGDRegressor(
                    learning_rate='adaptive',
                    eta0=self.LEARNING_RATE,
                    max_iter=1000,
                    random_state=42,
                    warm_start=True  # Allows incremental learning
                )
                sgd_model.fit(X_scaled, y)
                
                # Ensure base_time is datetime for consistent storage
                base_time = timestamps[0]
                if isinstance(base_time, date) and not isinstance(base_time, datetime):
                    base_time = datetime.combine(base_time, datetime.min.time())
                
                self.models[metric_name] = {
                    'type': 'sgd_continuous',
                    'model': sgd_model,
                    'base_time': base_time,
                    'supports_incremental': True
                }
                
                # Calculate initial performance
                y_pred = sgd_model.predict(X_scaled)
                r2 = r2_score(y, y_pred)
                mse = mean_squared_error(y, y_pred)
                
                self.model_metadata[metric_name]['initial_r2'] = r2
                self.model_metadata[metric_name]['initial_mse'] = mse
                
                logger.info(f"Trained SGD continuous learning model for {metric_name} (R²: {r2:.3f})")
            
            # Cache training data for incremental updates
            self.last_training_data[metric_name] = {
                'last_timestamp': max(entry['metric_timestamp'] for entry in historical_data),
                'data_points': len(historical_data),
                'last_values': y[-5:].tolist() if len(y) >= 5 else y.tolist()
            }
            
            # Save model to disk
            self._save_model(metric_name)
            
            logger.info(f"Successfully trained full model for {metric_name}")
            return True
            
        except Exception as e:
            logger.error(f"Full model training failed for {metric_name}: {str(e)}")
            return False
    
    def _update_model_incrementally(self, new_data: List[Dict], all_data: List[Dict], metric_name: str):
        """Update existing model with new data points using incremental learning."""
        try:
            model_info = self.models.get(metric_name)
            if not model_info or not model_info.get('supports_incremental', False):
                logger.info(f"Model for {metric_name} doesn't support incremental learning, doing full retrain")
                return self._train_full_model(all_data, metric_name)
            
            # Prepare new data
            X_new, y_new, timestamps_new = self.prepare_time_series_data(new_data, metric_name)
            
            if len(y_new) == 0:
                return True
            
            # Use the base_time from the original model for consistency
            base_time = model_info.get('base_time')
            if base_time:
                X_new = np.array([(ts - base_time).days for ts in timestamps_new]).reshape(-1, 1)
            
            # Scale new features
            scaler = self.scalers.get(metric_name)
            if scaler:
                X_new_scaled = scaler.transform(X_new)
            else:
                logger.warning(f"No scaler found for {metric_name}, using unscaled data")
                X_new_scaled = X_new
            
            # Incremental learning
            model = model_info['model']
            
            if model_info['type'] == 'sgd_continuous':
                # SGD supports partial_fit for incremental learning
                model.partial_fit(X_new_scaled, y_new)
                
                # Evaluate performance on new data
                y_pred_new = model.predict(X_new_scaled)
                r2_new = r2_score(y_new, y_pred_new) if len(y_new) > 1 else 0
                mse_new = mean_squared_error(y_new, y_pred_new)
                
                # Update metadata
                metadata = self.model_metadata[metric_name]
                metadata['last_incremental_update'] = datetime.now().isoformat()
                metadata['total_incremental_updates'] = metadata.get('total_incremental_updates', 0) + 1
                metadata['training_data_points'] += len(y_new)
                
                # Track performance history
                if 'performance_history' not in metadata:
                    metadata['performance_history'] = []
                
                metadata['performance_history'].append({
                    'timestamp': datetime.now().isoformat(),
                    'new_data_points': len(y_new),
                    'r2_on_new_data': r2_new,
                    'mse_on_new_data': mse_new,
                    'update_type': 'incremental'
                })
                
                # Keep only last 50 performance records
                metadata['performance_history'] = metadata['performance_history'][-50:]
                
                logger.info(f"Incrementally updated model for {metric_name} with {len(y_new)} new points (R²: {r2_new:.3f})")
            
            # Update cached training data
            self.last_training_data[metric_name] = {
                'last_timestamp': max(entry['metric_timestamp'] for entry in all_data),
                'data_points': len(all_data),
                'last_values': y_new[-5:].tolist() if len(y_new) >= 5 else y_new.tolist()
            }
            
            # Save updated model
            self._save_model(metric_name)
            
            return True
            
        except Exception as e:
            logger.error(f"Incremental model update failed for {metric_name}: {str(e)}")
            # Fallback to full retraining if incremental update fails
            return self._train_full_model(all_data, metric_name)
            
    def predict_metric(self, metric_name: str, periods: int = 14) -> Optional[Dict]:
        """Generate forecast for specified metric with enhanced continuous learning support."""
        if metric_name not in self.models:
            logger.warning(f"No trained model found for {metric_name}")
            return None
            
        try:
            model_info = self.models[metric_name]
            model_type = model_info['type']
            model = model_info['model']
            
            # Get model metadata for enhanced predictions
            metadata = self.model_metadata.get(metric_name, {})
            
            if model_type == 'arima':
                forecast, conf_int = model.predict(n_periods=periods, return_conf_int=True)
                forecast_dates = [datetime.now() + timedelta(days=i) for i in range(1, periods+1)]
                
                return {
                    'dates': [d.strftime('%Y-%m-%d') for d in forecast_dates],
                    'values': forecast.tolist(),
                    'confidence_intervals': conf_int.tolist(),
                    'metric': metric_name,
                    'model_type': 'arima',
                    'model_metadata': {
                        'training_points': metadata.get('training_data_points', 0),
                        'last_update': metadata.get('last_full_training', 'unknown'),
                        'supports_continuous_learning': False
                    }
                }
                
            elif model_type in ['linear', 'sgd_continuous']:
                base_time = model_info['base_time']
                future_dates = [datetime.now() + timedelta(days=i) for i in range(1, periods+1)]
                
                # Ensure base_time is datetime for proper arithmetic
                if isinstance(base_time, date) and not isinstance(base_time, datetime):
                    base_time = datetime.combine(base_time, datetime.min.time())
                
                future_X = np.array([(date - base_time).days for date in future_dates]).reshape(-1, 1)
                
                # Scale features if scaler exists
                scaler = self.scalers.get(metric_name)
                if scaler:
                    future_X_scaled = scaler.transform(future_X)
                else:
                    future_X_scaled = future_X
                
                predictions = model.predict(future_X_scaled)
                
                # Enhanced confidence intervals based on model performance
                if model_type == 'sgd_continuous':
                    # Use performance history to calculate dynamic confidence intervals
                    performance_history = metadata.get('performance_history', [])
                    if performance_history:
                        recent_mse = np.mean([p.get('mse_on_new_data', 0) for p in performance_history[-5:]])
                        confidence_width = np.sqrt(recent_mse) * 1.96  # 95% confidence
                    else:
                        confidence_width = np.std(predictions) if len(predictions) > 1 else predictions.std() * 0.1
                    
                    conf_intervals = [
                        [pred - confidence_width, pred + confidence_width] 
                        for pred in predictions
                    ]
                else:
                    # Simple confidence intervals for linear models
                    conf_intervals = [[pred * 0.9, pred * 1.1] for pred in predictions]
                
                return {
                    'dates': [d.strftime('%Y-%m-%d') for d in future_dates],
                    'values': predictions.tolist(),
                    'confidence_intervals': conf_intervals,
                    'metric': metric_name,
                    'model_type': model_type,
                    'model_metadata': {
                        'training_points': metadata.get('training_data_points', 0),
                        'last_full_training': metadata.get('last_full_training', 'unknown'),
                        'last_incremental_update': metadata.get('last_incremental_update', 'none'),
                        'incremental_updates': metadata.get('total_incremental_updates', 0),
                        'supports_continuous_learning': model_info.get('supports_incremental', False),
                        'model_version': metadata.get('model_version', 1)
                    }
                }
                
        except Exception as e:
            logger.error(f"Prediction failed for {metric_name}: {str(e)}")
            return None
    
    def get_model_learning_status(self, metric_name: str) -> Dict[str, Any]:
        """Get detailed status of model's continuous learning progress."""
        if metric_name not in self.models:
            return {"error": "Model not found"}
        
        try:
            model_info = self.models[metric_name]
            metadata = self.model_metadata.get(metric_name, {})
            
            status = {
                "model_type": model_info['type'],
                "supports_continuous_learning": model_info.get('supports_incremental', False),
                "training_data_points": metadata.get('training_data_points', 0),
                "last_full_training": metadata.get('last_full_training', 'unknown'),
                "last_incremental_update": metadata.get('last_incremental_update', 'none'),
                "total_incremental_updates": metadata.get('total_incremental_updates', 0),
                "model_version": metadata.get('model_version', 1)
            }
            
            # Performance trend analysis
            performance_history = metadata.get('performance_history', [])
            if performance_history:
                recent_performance = performance_history[-5:]  # Last 5 updates
                avg_recent_r2 = np.mean([p.get('r2_on_new_data', 0) for p in recent_performance])
                avg_recent_mse = np.mean([p.get('mse_on_new_data', 0) for p in recent_performance])
                
                status.update({
                    "recent_performance": {
                        "avg_r2_last_5_updates": round(avg_recent_r2, 3),
                        "avg_mse_last_5_updates": round(avg_recent_mse, 3),
                        "performance_trend": "improving" if len(recent_performance) > 1 and 
                                           recent_performance[-1].get('r2_on_new_data', 0) > recent_performance[0].get('r2_on_new_data', 0)
                                           else "stable"
                    },
                    "learning_history": performance_history[-10:]  # Last 10 updates
                })
            
            # Model age and freshness
            if metadata.get('last_full_training'):
                try:
                    last_training = datetime.fromisoformat(metadata['last_full_training'])
                    days_since_training = (datetime.now() - last_training).days
                    status['days_since_full_training'] = days_since_training
                    status['model_freshness'] = 'fresh' if days_since_training < 7 else 'aging' if days_since_training < 30 else 'stale'
                except:
                    pass
            
            return status
            
        except Exception as e:
            logger.error(f"Failed to get learning status for {metric_name}: {e}")
            return {"error": str(e)}
            
    def _extract_nested_metric(self, metrics: Dict, metric_path: str) -> Optional[float]:
        """Extract nested metric value using dot notation (e.g., 'dora.lead_time.total_lead_time_hours')."""
        try:
            keys = metric_path.split('.')
            value = metrics
            
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return None
                    
            return float(value) if value is not None else None
        except (ValueError, TypeError):
            return None
            
    def predict_trend(self, historical_data: List[Dict], metric_name: str, days_ahead: int = 14) -> Dict[str, Any]:
        """Predict future trends using multiple algorithms."""
        X, y, timestamps = self.prepare_time_series_data(historical_data, metric_name)
        
        if len(X) < 3:
            return {
                "prediction": None,
                "confidence": 0,
                "trend": "insufficient_data",
                "error": "Need at least 3 data points for prediction"
            }
            
        predictions = {}
        models_performance = {}
        
        # Linear Regression
        try:
            lr_model = LinearRegression()
            lr_model.fit(X, y)
            future_day = X[-1][0] + days_ahead
            lr_pred = lr_model.predict([[future_day]])[0]
            lr_score = r2_score(y, lr_model.predict(X))
            predictions['linear'] = lr_pred
            models_performance['linear'] = lr_score
        except Exception as e:
            logger.warning(f"Linear regression failed: {e}")
            
        # Ridge Regression
        try:
            ridge_model = Ridge(alpha=1.0)
            ridge_model.fit(X, y)
            future_day = X[-1][0] + days_ahead
            ridge_pred = ridge_model.predict([[future_day]])[0]
            ridge_score = r2_score(y, ridge_model.predict(X))
            predictions['ridge'] = ridge_pred
            models_performance['ridge'] = ridge_score
        except Exception as e:
            logger.warning(f"Ridge regression failed: {e}")
            
        # Random Forest (for larger datasets)
        if len(X) >= 5:
            try:
                rf_model = RandomForestRegressor(n_estimators=50, random_state=42)
                rf_model.fit(X, y)
                future_day = X[-1][0] + days_ahead
                rf_pred = rf_model.predict([[future_day]])[0]
                rf_score = r2_score(y, rf_model.predict(X))
                predictions['random_forest'] = rf_pred
                models_performance['random_forest'] = rf_score
            except Exception as e:
                logger.warning(f"Random forest failed: {e}")
                
        if not predictions:
            return {
                "prediction": None,
                "confidence": 0,
                "trend": "prediction_failed",
                "error": "All prediction models failed"
            }
            
        # Ensemble prediction (weighted by performance)
        total_weight = sum(max(0, score) for score in models_performance.values())
        if total_weight > 0:
            weighted_pred = sum(
                pred * max(0, models_performance[model]) / total_weight
                for model, pred in predictions.items()
            )
        else:
            weighted_pred = np.mean(list(predictions.values()))
            
        # Calculate trend direction
        if len(y) >= 2:
            recent_trend = np.polyfit(range(len(y)), y, 1)[0]
            if recent_trend > 0.1:
                trend_direction = "increasing"
            elif recent_trend < -0.1:
                trend_direction = "decreasing"
            else:
                trend_direction = "stable"
        else:
            trend_direction = "unknown"
            
        # Calculate confidence
        pred_variance = np.var(list(predictions.values())) if len(predictions) > 1 else 0
        historical_variance = np.var(y) if len(y) > 1 else 0
        
        if historical_variance > 0:
            confidence = max(0, min(100, 100 - (pred_variance / historical_variance) * 100))
        else:
            confidence = 50
            
        return {
            "prediction": round(weighted_pred, 2),
            "confidence": round(confidence, 1),
            "trend": trend_direction,
            "model_predictions": predictions,
            "model_performance": models_performance,
            "prediction_date": (timestamps[-1] + timedelta(days=days_ahead)).isoformat(),
            "historical_variance": round(historical_variance, 2),
            "prediction_variance": round(pred_variance, 2)
        }
        
    def detect_anomalies(self, historical_data: List[Dict], metric_name: str) -> Dict[str, Any]:
        """Enhanced anomaly detection with multiple methods and error handling."""
        X, y, timestamps = self.prepare_time_series_data(historical_data, metric_name)
        
        if len(y) < 5:
            return {
                "anomalies": [],
                "anomaly_score": 0,
                "method": "insufficient_data",
                "total_data_points": len(y)
            }
            
        anomalies = []
        methods_used = []
        
        # Isolation Forest
        try:
            iso_forest = IsolationForest(contamination=self.ANOMALY_IFOREST_CONTAM, random_state=42)
            y_reshaped = y.reshape(-1, 1)
            anomaly_labels = iso_forest.fit_predict(y_reshaped)
            
            for i, (is_anomaly, timestamp, value) in enumerate(zip(anomaly_labels, timestamps, y)):
                if is_anomaly == -1:
                    anomalies.append({
                        "index": i,
                        "timestamp": timestamp.isoformat(),
                        "value": float(value),
                        "method": "isolation_forest",
                        "severity": abs(float(iso_forest.score_samples(y_reshaped)[i]))
                    })
            methods_used.append("isolation_forest")
        except Exception as e:
            logger.warning(f"Isolation forest failed: {e}")
            
        # Z-score method
        try:
            if len(y) > 1:
                mean_val = np.mean(y)
                std_val = np.std(y)
                
                if std_val > 0:
                    z_scores = np.abs((y - mean_val) / std_val)
                    
                    for i, (z_score, timestamp, value) in enumerate(zip(z_scores, timestamps, y)):
                        if z_score > self.ANOMALY_Z_THRESHOLD:
                            anomalies.append({
                                "index": i,
                                "timestamp": timestamp.isoformat(),
                                "value": float(value),
                                "method": "z_score",
                                "severity": float(z_score),
                                "z_score": round(float(z_score), 2)
                            })
                    methods_used.append("z_score")
        except Exception as e:
            logger.warning(f"Z-score anomaly detection failed: {e}")
            
        # Moving average deviation
        try:
            if len(y) >= self.MOVING_AVG_WINDOW:
                window_size = min(self.MOVING_AVG_WINDOW, len(y) // 2)
                moving_avg = []
                
                for i in range(len(y)):
                    start_idx = max(0, i - window_size // 2)
                    end_idx = min(len(y), i + window_size // 2 + 1)
                    moving_avg.append(np.mean(y[start_idx:end_idx]))
                    
                deviations = np.abs(y - np.array(moving_avg))
                threshold = np.std(deviations) * 2
                
                for i, (deviation, timestamp, value) in enumerate(zip(deviations, timestamps, y)):
                    if deviation > threshold:
                        anomalies.append({
                            "index": i,
                            "timestamp": timestamp.isoformat(),
                            "value": float(value),
                            "method": "moving_average",
                            "severity": float(deviation),
                            "deviation": round(float(deviation), 2)
                        })
                methods_used.append("moving_average")
        except Exception as e:
            logger.warning(f"Moving average anomaly detection failed: {e}")
            
        # Remove duplicates based on index
        unique_anomalies = []
        seen_indices = set()
        for anomaly in sorted(anomalies, key=lambda x: x['timestamp']):
            if anomaly['index'] not in seen_indices:
                unique_anomalies.append(anomaly)
                seen_indices.add(anomaly['index'])
                
        anomaly_score = len(unique_anomalies) / len(y) * 100 if len(y) > 0 else 0
        
        return {
            "anomalies": unique_anomalies,
            "anomaly_score": round(anomaly_score, 1),
            "total_data_points": len(y),
            "anomaly_count": len(unique_anomalies),
            "methods_used": methods_used
        }
        
    def analyze_developer_clusters(self, user_metrics: List[Dict]) -> Dict[str, Any]:
        """Cluster developers based on their performance patterns."""
        if len(user_metrics) < self.MIN_CLUSTER_USERS:
            return {"error": "Need at least 3 developers for clustering"}
            
        features = []
        user_ids = []
        
        for user_data in user_metrics:
            try:
                metrics = user_data.get('metrics', {})
                feature_vector = [
                    self._extract_nested_metric(metrics, 'dora.lead_time.total_lead_time_hours') or 0,
                    self._extract_nested_metric(metrics, 'dora.deployment_frequency.per_week') or 0,
                    self._extract_nested_metric(metrics, 'dora.change_failure_rate.percentage') or 0,
                    self._extract_nested_metric(metrics, 'code_quality.review_coverage_percentage') or 0,
                    self._extract_nested_metric(metrics, 'productivity_patterns.max_commit_streak') or 0,
                    self._extract_nested_metric(metrics, 'collaboration.unique_reviewers') or 0
                ]
                
                if any(f != 0 for f in feature_vector):
                    features.append(feature_vector)
                    user_ids.append(user_data.get('user_id', f'user_{len(features)}'))
            except Exception as e:
                logger.warning(f"Failed to extract features for user: {e}")
                continue
                
        if len(features) < self.MIN_CLUSTER_USERS:
            return {"error": "Insufficient valid feature data for clustering"}
            
        # Scale features
        scaler = StandardScaler()
        features_scaled = scaler.fit_transform(features)
        
        # Perform clustering
        n_clusters = min(4, len(features))
        kmeans = KMeans(n_clusters=n_clusters, random_state=42)
        cluster_labels = kmeans.fit_predict(features_scaled)
        
        # Analyze clusters
        clusters = {}
        for i in range(n_clusters):
            cluster_indices = [j for j, label in enumerate(cluster_labels) if label == i]
            cluster_features = [features[j] for j in cluster_indices]
            
            if cluster_features:
                avg_features = np.mean(cluster_features, axis=0)
                clusters[f"cluster_{i}"] = {
                    "members": [user_ids[j] for j in cluster_indices],
                    "size": len(cluster_indices),
                    "characteristics": {
                        "avg_lead_time_hours": round(avg_features[0], 2),
                        "avg_deployment_frequency": round(avg_features[1], 2),
                        "avg_failure_rate": round(avg_features[2], 2),
                        "avg_review_coverage": round(avg_features[3], 2),
                        "avg_commit_streak": round(avg_features[4], 2),
                        "avg_collaborators": round(avg_features[5], 2)
                    }
                }
                
        cluster_descriptions = self._generate_cluster_descriptions(clusters)
        
        return {
            "clusters": clusters,
            "cluster_descriptions": cluster_descriptions,
            "total_developers": len(features),
            "clustering_features": [
                "lead_time", "deployment_frequency", "failure_rate",
                "review_coverage", "commit_streak", "collaboration"
            ]
        }
        
    def _generate_cluster_descriptions(self, clusters: Dict) -> Dict[str, str]:
        """Generate human-readable descriptions for clusters."""
        descriptions = {}
        
        for cluster_id, cluster_data in clusters.items():
            chars = cluster_data["characteristics"]
            
            if chars["avg_lead_time_hours"] < 24 and chars["avg_deployment_frequency"] > 3:
                desc = "High Performers - Fast delivery with frequent deployments"
            elif chars["avg_failure_rate"] < 10 and chars["avg_review_coverage"] > 80:
                desc = "Quality Focused - Emphasize code quality and thorough reviews"
            elif chars["avg_commit_streak"] > 7 and chars["avg_collaborators"] > 3:
                desc = "Consistent Collaborators - Regular contributors with strong teamwork"
            elif chars["avg_lead_time_hours"] > 168:  # > 1 week
                desc = "Deliberate Developers - Take time for thorough development"
            else:
                desc = "Balanced Contributors - Well-rounded development approach"
                
            descriptions[cluster_id] = desc
            
        return descriptions
        
    def generate_insights(self, metrics: Dict[str, Any], historical_data: List[Dict] = None) -> Dict[str, Any]:
        """Generate actionable insights from metrics and trends."""
        insights = {
            "performance_insights": [],
            "trend_insights": [],
            "recommendations": [],
            "alerts": []
        }
        
        # Performance insights
        perf_grade = metrics.get("performance_grade", {})
        if perf_grade:
            grade = perf_grade.get("overall_grade", "")
            percentage = perf_grade.get("percentage", 0)
            
            if percentage >= 85:
                insights["performance_insights"].append(
                    f"Excellent performance with {grade} grade ({percentage}%)")
            elif percentage >= 70:
                insights["performance_insights"].append(
                    f"Good performance with {grade} grade ({percentage}%) - room for improvement")
            else:
                insights["performance_insights"].append(
                    f"Performance needs attention with {grade} grade ({percentage}%)")
                    
        # DORA metrics insights
        dora = metrics.get("dora", {})
        if dora:
            lead_time = dora.get("lead_time", {}).get("total_lead_time_hours", 0)
            deploy_freq = dora.get("deployment_frequency", {}).get("per_week", 0)
            failure_rate = dora.get("change_failure_rate", {}).get("percentage", 0)
            
            if lead_time > 168:  # > 1 week
                insights["alerts"].append("Lead time is longer than industry average")
                insights["recommendations"].append("Consider breaking down work into smaller, reviewable chunks")
                
            if deploy_freq < 1:
                insights["alerts"].append("Low deployment frequency detected")
                insights["recommendations"].append("Increase deployment cadence with smaller, more frequent releases")
                
            if failure_rate > 15:
                insights["alerts"].append("High change failure rate")
                insights["recommendations"].append("Invest in automated testing and code review processes")
                
        # Trend analysis if historical data available
        if historical_data and len(historical_data) > 1:
            # Analyze lead time trend
            lead_time_trend = self.predict_trend(historical_data, "dora.lead_time.total_lead_time_hours")
            if lead_time_trend.get("trend") == "increasing":
                insights["trend_insights"].append("Lead time is trending upward - investigate bottlenecks")
            elif lead_time_trend.get("trend") == "decreasing":
                insights["trend_insights"].append("Lead time is improving - great progress!")
                
            # Check for anomalies
            anomalies = self.detect_anomalies(historical_data, "dora.deployment_frequency.per_week")
            if anomalies.get("anomaly_score", 0) > 20:
                insights["alerts"].append("Unusual patterns detected in deployment frequency")
                
        # Code quality insights
        code_quality = metrics.get("code_quality", {})
        if code_quality:
            review_coverage = code_quality.get("review_coverage_percentage", 0)
            large_prs = code_quality.get("large_prs_percentage", 0)
            
            if review_coverage < 70:
                insights["recommendations"].append("Increase code review coverage for better quality")
            if large_prs > 25:
                insights["recommendations"].append("Break down large PRs for easier reviews and faster merges")
                
        # Productivity patterns
        productivity = metrics.get("productivity_patterns", {})
        if productivity:
            work_life_balance = productivity.get("work_life_balance_score", 0)
            if work_life_balance < 60:
                insights["recommendations"].append("Consider improving work-life balance - avoid excessive weekend/late-night work")
                
        return insights
        
    def forecast_performance_grade(self, historical_data: List[Dict], weeks_ahead: int = 4) -> Dict[str, Any]:
        """Forecast future performance grade based on historical trends."""
        if len(historical_data) < 3:
            return {"error": "Insufficient historical data for forecasting"}
            
        # Extract performance grades over time
        grades = []
        timestamps = []
        
        for entry in sorted(historical_data, key=lambda x: x['metric_timestamp']):
            try:
                timestamp = datetime.fromisoformat(entry['metric_timestamp'].replace('Z', '+00:00'))
                grade_data = entry.get('metrics_data', {}).get('performance_grade', {})
                percentage = grade_data.get('percentage', 0)
                
                if percentage > 0:
                    grades.append(percentage)
                    timestamps.append(timestamp)
            except Exception as e:
                continue
                
        if len(grades) < 3:
            return {"error": "Insufficient performance grade data"}
            
        # Prepare data for prediction
        base_time = timestamps[0]
        
        # Ensure base_time is datetime for proper arithmetic
        if isinstance(base_time, date) and not isinstance(base_time, datetime):
            base_time = datetime.combine(base_time, datetime.min.time())
            
        # Convert all timestamps to datetime for consistent arithmetic
        datetime_timestamps = []
        for ts in timestamps:
            if isinstance(ts, datetime):
                datetime_timestamps.append(ts)
            elif isinstance(ts, date):
                datetime_timestamps.append(datetime.combine(ts, datetime.min.time()))
            else:
                datetime_timestamps.append(ts)
                
        X = np.array([(ts - base_time).days for ts in datetime_timestamps]).reshape(-1, 1)
        y = np.array(grades)
        
        # Use linear regression for trend
        model = LinearRegression()
        model.fit(X, y)
        
        # Predict future
        future_day = X[-1][0] + (weeks_ahead * 7)
        predicted_percentage = model.predict([[future_day]])[0]
        
        # Convert percentage to grade
        predicted_grade = self._percentage_to_grade(predicted_percentage)
        
        # Calculate confidence based on R²
        confidence = max(0, min(100, r2_score(y, model.predict(X)) * 100))
        
        return {
            "predicted_grade": predicted_grade,
            "predicted_percentage": round(max(0, min(100, predicted_percentage)), 1),
            "confidence": round(confidence, 1),
            "trend": "improving" if model.coef_[0] > 0 else "declining" if model.coef_[0] < 0 else "stable",
            "forecast_date": (timestamps[-1] + timedelta(weeks=weeks_ahead)).isoformat()
        }
        
    def _percentage_to_grade(self, percentage: float) -> str:
        """Convert percentage to letter grade."""
        if percentage >= 90: return "A+"
        elif percentage >= 85: return "A"
        elif percentage >= 80: return "A-"
        elif percentage >= 75: return "B+"
        elif percentage >= 70: return "B"
        elif percentage >= 65: return "B-"
        elif percentage >= 60: return "C+"
        elif percentage >= 55: return "C"
        else: return "C-"
        
    def predict_performance_degradation(self, historical_data: List[Dict]) -> Dict[str, Any]:
        """Predict performance degradation using change point detection"""
        try:
            if len(historical_data) < 10:
                return {
                    "error": "Insufficient data for degradation prediction",
                    "risk_level": "unknown"
                }
                
            # Extract performance scores over time
            scores = []
            timestamps = []
            
            for entry in sorted(historical_data, key=lambda x: x.get('metric_timestamp', '')):
                try:
                    timestamp = datetime.fromisoformat(entry['metric_timestamp'].replace('Z', '+00:00'))
                    perf_data = entry.get('metrics_data', {}).get('performance_grade', {})
                    score = perf_data.get('percentage', 0)
                    
                    if score > 0:
                        scores.append(score)
                        timestamps.append(timestamp)
                except Exception:
                    continue
                    
            if len(scores) < 5:
                return {
                    "error": "Insufficient performance data",
                    "risk_level": "unknown"
                }
                
            # Simple trend analysis
            recent_scores = scores[-5:]  # Last 5 data points
            older_scores = scores[:-5] if len(scores) > 5 else scores[:len(scores)//2]
            
            recent_avg = np.mean(recent_scores)
            older_avg = np.mean(older_scores) if older_scores else recent_avg
            
            # Calculate trend
            trend_change = (recent_avg - older_avg) / older_avg * 100 if older_avg > 0 else 0
            
            # Determine risk level
            if trend_change < -15:
                risk_level = "high"
                prediction = "Performance degradation detected - significant decline in recent metrics"
            elif trend_change < -5:
                risk_level = "medium"
                prediction = "Moderate performance decline observed"
            elif trend_change > 10:
                risk_level = "low"
                prediction = "Performance improving - positive trend detected"
            else:
                risk_level = "low"
                prediction = "Performance stable - no significant degradation detected"
                
            # Calculate volatility
            score_std = np.std(scores)
            volatility = "high" if score_std > 15 else "medium" if score_std > 8 else "low"
            
            return {
                "risk_level": risk_level,
                "prediction": prediction,
                "trend_change_percentage": round(trend_change, 2),
                "recent_average": round(recent_avg, 1),
                "historical_average": round(older_avg, 1),
                "volatility": volatility,
                "confidence": min(100, max(10, 100 - score_std))  # Higher std = lower confidence
            }
            
        except Exception as e:
            logger.error(f"Performance degradation prediction failed: {str(e)}")
            return {
                "error": str(e),
                "risk_level": "unknown",
                "prediction": "Unable to assess performance degradation risk"
            }
            
    def identify_bottlenecks(self, metrics: Dict[str, Any]) -> List[str]:
        """Identify potential bottlenecks in development workflow"""
        bottlenecks = []
        
        try:
            # Check DORA metrics for bottlenecks
            dora = metrics.get('dora', {})
            
            # Lead time bottlenecks
            lead_time_data = dora.get('lead_time', {})
            review_time = lead_time_data.get('review_time_hours', 0)
            merge_time = lead_time_data.get('merge_time_hours', 0)
            code_time = lead_time_data.get('code_time_hours', 0)
            
            if review_time > 24:
                bottlenecks.append("Code review process - reviews taking longer than 24 hours")
            if merge_time > 12:
                bottlenecks.append("Merge/Deployment process - long time from approval to merge")
            if code_time > 48:
                bottlenecks.append("Development process - long time from first commit to PR creation")
                
            # Deployment frequency bottlenecks
            deploy_freq = dora.get('deployment_frequency', {}).get('per_week', 0)
            if deploy_freq < 1:
                bottlenecks.append("Deployment pipeline - infrequent deployments suggest process issues")
                
            # Change failure rate bottlenecks
            failure_rate = dora.get('change_failure_rate', {}).get('percentage', 0)
            if failure_rate > 15:
                bottlenecks.append("Quality assurance - high failure rate indicates testing gaps")
                
            # Code quality bottlenecks
            code_quality = metrics.get('code_quality', {})
            review_coverage = code_quality.get('review_coverage_percentage', 0)
            large_prs_pct = code_quality.get('large_prs_percentage', 0)
            
            if review_coverage < 70:
                bottlenecks.append("Review coverage - insufficient code review coverage")
            if large_prs_pct > 25:
                bottlenecks.append("Pull request sizing - too many large PRs slowing down reviews")
                
            # Collaboration bottlenecks
            collaboration = metrics.get('collaboration', {})
            unique_reviewers = collaboration.get('unique_reviewers', 0)
            review_response_time = collaboration.get('avg_review_response_time_hours', 0)
            
            if unique_reviewers < 2:
                bottlenecks.append("Review diversity - limited number of reviewers creates dependency")
            if review_response_time > 48:
                bottlenecks.append("Review responsiveness - slow review response times")
                
            # Work patterns bottlenecks
            productivity = metrics.get('productivity_patterns', {})
            weekend_work = productivity.get('weekend_work_percentage', 0)
            
            if weekend_work > 20:
                bottlenecks.append("Work-life balance - excessive weekend work may lead to burnout")
                
            return bottlenecks
            
        except Exception as e:
            logger.error(f"Bottleneck identification failed: {str(e)}")
            return ["Unable to identify bottlenecks due to data processing error"]
            
    def analyze_technical_debt_indicators(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze indicators of technical debt accumulation"""
        try:
            debt_indicators = {
                "debt_score": 0,
                "risk_factors": [],
                "recommendations": []
            }
            
            # Check code quality metrics
            code_quality = metrics.get('code_quality', {})
            
            # Large commits/PRs indicate rushed work
            large_commits_pct = code_quality.get('large_commits_percentage', 0)
            large_prs_pct = code_quality.get('large_prs_percentage', 0)
            
            if large_commits_pct > 20:
                debt_indicators["debt_score"] += 15
                debt_indicators["risk_factors"].append("Frequent large commits")
                debt_indicators["recommendations"].append("Break down work into smaller, reviewable chunks")
                
            if large_prs_pct > 25:
                debt_indicators["debt_score"] += 10
                debt_indicators["risk_factors"].append("Large pull requests")
                
            # Review coverage affects code quality
            review_coverage = code_quality.get('review_coverage_percentage', 0)
            if review_coverage < 70:
                debt_indicators["debt_score"] += 20
                debt_indicators["risk_factors"].append("Insufficient code review coverage")
                debt_indicators["recommendations"].append("Increase code review coverage to catch issues early")
                
            # High failure rate suggests quality issues
            failure_rate = metrics.get('dora', {}).get('change_failure_rate', {}).get('percentage', 0)
            if failure_rate > 15:
                debt_indicators["debt_score"] += 25
                debt_indicators["risk_factors"].append("High change failure rate")
                debt_indicators["recommendations"].append("Invest in automated testing and quality gates")
                
            # Fast delivery without quality checks
            lead_time = metrics.get('dora', {}).get('lead_time', {}).get('total_lead_time_hours', 0)
            if lead_time < 2 and review_coverage < 50:  # Very fast but unreviewed
                debt_indicators["debt_score"] += 15
                debt_indicators["risk_factors"].append("Very fast delivery with minimal review")
                
            # Determine debt level
            score = debt_indicators["debt_score"]
            if score < 20:
                debt_indicators["debt_level"] = "Low"
            elif score < 40:
                debt_indicators["debt_level"] = "Medium"
            elif score < 60:
                debt_indicators["debt_level"] = "High"
            else:
                debt_indicators["debt_level"] = "Critical"
                
            return debt_indicators
            
        except Exception as e:
            logger.error(f"Technical debt analysis failed: {str(e)}")
            return {
                "debt_score": 0,
                "debt_level": "Unknown",
                "risk_factors": [],
                "recommendations": [],
                "error": str(e)
            }

    def get_continuous_learning_status(self, historical_data: List[Dict] = None) -> Dict[str, Any]:
        """Get comprehensive continuous learning status for all models."""
        try:
            total_models = len(self.models)
            continuously_learning_models = 0
            models_updated_recently = 0
            model_details = []
            
            # Common metrics to track
            key_metrics = [
                "dora.lead_time.total_lead_time_hours",
                "total_commits", 
                "total_prs",
                "activity_score",
                "performance_score"
            ]
            
            # If we have historical data, try to train/update models
            if historical_data and len(historical_data) >= self.MIN_FORECAST_POINTS:
                for metric_name in key_metrics:
                    try:
                        # Try to train or update model
                        success = self.train_forecasting_model(historical_data, metric_name)
                        if success and metric_name in self.models:
                            model_info = self.models[metric_name]
                            metadata = self.model_metadata.get(metric_name, {})
                            
                            supports_learning = model_info.get('supports_incremental', False)
                            if supports_learning:
                                continuously_learning_models += 1
                            
                            # Check if updated recently
                            last_update = metadata.get('last_incremental_update')
                            if last_update:
                                try:
                                    update_time = datetime.fromisoformat(last_update)
                                    if (datetime.now() - update_time).days < 1:
                                        models_updated_recently += 1
                                except:
                                    pass
                            
                            model_details.append({
                                "metric": metric_name,
                                "type": model_info['type'],
                                "supports_learning": supports_learning,
                                "training_points": metadata.get('training_data_points', 0),
                                "performance": metadata.get('performance_history', [])[-1:] if metadata.get('performance_history') else []
                            })
                    except Exception as e:
                        logger.debug(f"Failed to process model for {metric_name}: {e}")
                        continue
            
            # Calculate learning percentage
            learning_percentage = round((continuously_learning_models / max(total_models, 1)) * 100) if total_models > 0 else 0
            
            # Generate status message
            if total_models == 0:
                status = "no_models"
                message = "No ML models available yet. Need more historical data."
            elif continuously_learning_models == total_models:
                status = "all_learning"
                message = f"All {total_models} models support continuous learning and are active!"
            elif continuously_learning_models > 0:
                status = "partial_learning"
                message = f"{continuously_learning_models} of {total_models} models support continuous learning."
            else:
                status = "no_learning"
                message = "Models are trained but haven't received incremental updates yet. They will learn automatically as new data comes in!"
            
            return {
                "status": status,
                "total_models": total_models,
                "continuously_learning_models": continuously_learning_models,
                "learning_percentage": learning_percentage,
                "models_updated_recently": models_updated_recently,
                "message": message,
                "model_details": model_details,
                "data_points_available": len(historical_data) if historical_data else 0,
                "minimum_required": self.MIN_FORECAST_POINTS
            }
            
        except Exception as e:
            logger.error(f"Error getting continuous learning status: {e}")
            return {
                "status": "error",
                "error": str(e),
                "total_models": 0,
                "continuously_learning_models": 0,
                "learning_percentage": 0,
                "models_updated_recently": 0,
                "message": "Error retrieving learning status"
            }
