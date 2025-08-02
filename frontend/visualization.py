import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union
import logging

logger = logging.getLogger(__name__)

def parse_timestamp(timestamp_str) -> datetime:
    """Parse timestamp string with flexible fractional seconds handling."""
    try:
        # If it's already a datetime object, return it
        if isinstance(timestamp_str, datetime):
            return timestamp_str
            
        # Convert to string if it's not
        timestamp_str = str(timestamp_str)
        
        # Handle date-only strings (YYYY-MM-DD)
        if len(timestamp_str) == 10 and timestamp_str.count('-') == 2:
            return datetime.strptime(timestamp_str, '%Y-%m-%d')
        
        # Handle Z timezone indicator
        if timestamp_str.endswith('Z'):
            timestamp_str = timestamp_str.replace('Z', '+00:00')
        
        # Handle fractional seconds that might be too long for fromisoformat
        # Find the position of the fractional seconds
        if '.' in timestamp_str and ('+' in timestamp_str or '-' in timestamp_str[-6:]):  # Check last 6 chars for timezone
            # Split at timezone
            if '+' in timestamp_str:
                dt_part, tz_part = timestamp_str.rsplit('+', 1)
                tz_part = '+' + tz_part
            else:
                dt_part, tz_part = timestamp_str.rsplit('-', 1)
                # Make sure this is actually a timezone, not part of the date
                if len(tz_part) <= 5 and ':' in tz_part:
                    tz_part = '-' + tz_part
                else:
                    # It's part of the date, put it back
                    dt_part = timestamp_str
                    tz_part = ''
            
            # Limit fractional seconds to 6 digits
            if '.' in dt_part:
                dt_base, fractional = dt_part.split('.')
                fractional = fractional[:6].ljust(6, '0')  # Pad or truncate to 6 digits
                timestamp_str = f"{dt_base}.{fractional}{tz_part}"
        
        return datetime.fromisoformat(timestamp_str)
    except ValueError:
        # Fallback: try without fractional seconds
        try:
            timestamp_str = str(timestamp_str).split('.')[0]
            if timestamp_str.endswith('Z'):
                timestamp_str = timestamp_str.replace('Z', '+00:00')
            return datetime.fromisoformat(timestamp_str)
        except ValueError:
            # Final fallback: try basic date parsing
            try:
                return datetime.strptime(timestamp_str, '%Y-%m-%d')
            except ValueError:
                # If all else fails, return current time
                logger.warning(f"Could not parse timestamp: {timestamp_str}")
                return datetime.now()

# Color palettes and themes
COLORBLIND_PALETTE = ["#0072B2", "#E69F00", "#56B4E9", "#009E73", "#F0E442", "#D55E00", "#CC79A7"]
DARK_MODE = False  # Set to True for dark backgrounds

def get_bgcolor():
    return "#222" if DARK_MODE else "white"

def create_continuous_learning_status_chart(learning_data: Dict[str, Any]) -> go.Figure:
    """Create a visual representation of continuous learning model status."""
    try:
        if not learning_data or learning_data.get("status") == "no_models":
            fig = go.Figure()
            fig.add_annotation(
                text="No ML models available for continuous learning",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=16)
            )
            fig.update_layout(
                title="🧠 Continuous Learning Status",
                showlegend=False,
                height=300
            )
            return fig
        
        # Extract model details
        model_details = learning_data.get("model_details", [])
        total_models = learning_data.get("total_models", 0)
        continuously_learning = learning_data.get("continuously_learning_models", 0)
        learning_percentage = learning_data.get("learning_percentage", 0)
        
        # Convert list of model details to easier format for processing
        if isinstance(model_details, list):
            model_dict = {detail.get("metric", f"model_{i}"): detail for i, detail in enumerate(model_details)}
        else:
            model_dict = model_details
        
        # Create subplots
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                "Learning Capability Overview",
                "Model Freshness Status", 
                "Incremental Updates Count",
                "Training Data Points"
            ),
            specs=[
                [{"type": "indicator"}, {"type": "pie"}],
                [{"type": "bar"}, {"type": "bar"}]
            ]
        )
        
        # 1. Learning percentage gauge
        fig.add_trace(
            go.Indicator(
                mode="gauge+number+delta",
                value=learning_percentage,
                domain={'x': [0, 1], 'y': [0, 1]},
                title={'text': "% Models with Continuous Learning"},
                gauge={
                    'axis': {'range': [None, 100]},
                    'bar': {'color': COLORBLIND_PALETTE[3]},  # Green
                    'steps': [
                        {'range': [0, 50], 'color': "lightgray"},
                        {'range': [50, 80], 'color': "yellow"},
                        {'range': [80, 100], 'color': "lightgreen"}
                    ],
                    'threshold': {
                        'line': {'color': "red", 'width': 4},
                        'thickness': 0.75,
                        'value': 90
                    }
                }
            ),
            row=1, col=1
        )
        
        # 2. Model freshness pie chart (simplified since we don't have freshness data yet)
        learning_counts = {"Learning": continuously_learning, "Static": total_models - continuously_learning}
        
        if learning_counts:
            fig.add_trace(
                go.Pie(
                    labels=list(learning_counts.keys()),
                    values=list(learning_counts.values()),
                    marker_colors=[COLORBLIND_PALETTE[3], COLORBLIND_PALETTE[6]]  # Green and gray
                ),
                row=1, col=2
            )
        
        # 3. Model types bar chart
        model_names = []
        model_types = []
        
        for model_name, details in model_dict.items():
            # Shorten model names for display
            display_name = model_name.split(".")[-1] if "." in model_name else model_name
            model_names.append(display_name)
            model_types.append(1)  # Count of models by type
        
        if model_names:
            fig.add_trace(
                go.Bar(
                    x=model_names,
                    y=model_types,
                    marker_color=COLORBLIND_PALETTE[1],  # Orange
                    name="Models Count"
                ),
                row=2, col=1
            )
        
        # 4. Training data points bar chart
        data_points = []
        for model_name, details in model_dict.items():
            data_points.append(details.get("training_points", 0))
        
        if model_names and data_points:
            fig.add_trace(
                go.Bar(
                    x=model_names,
                    y=data_points,
                    marker_color=COLORBLIND_PALETTE[0],  # Blue
                    name="Training Data Points"
                ),
                row=2, col=2
            )
        
        fig.add_trace(
            go.Bar(
                x=model_names,
                y=data_points,
                marker_color=COLORBLIND_PALETTE[0],  # Blue
                name="Training Data Points"
            ),
            row=2, col=2
        )
        
        # Update layout
        fig.update_layout(
            title={
                'text': f"🧠 Continuous Learning Dashboard - {learning_data.get('message', '')}",
                'x': 0.5,
                'xanchor': 'center'
            },
            height=600,
            showlegend=False,
            paper_bgcolor=get_bgcolor(),
            plot_bgcolor=get_bgcolor()
        )
        
        # Update x-axis labels for bar charts
        fig.update_xaxes(tickangle=45, row=2, col=1)
        fig.update_xaxes(tickangle=45, row=2, col=2)
        
        return fig
        
    except Exception as e:
        logger.error(f"Failed to create continuous learning status chart: {e}")
        # Return empty figure with error message
        fig = go.Figure()
        fig.add_annotation(
            text=f"Error creating learning status chart: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="red")
        )
        fig.update_layout(title="🧠 Continuous Learning Status - Error", height=300)
        return fig

def create_ml_forecast_comparison_chart(ml_predictions: Dict[str, Any]) -> go.Figure:
    """Create a chart comparing ML forecasts across different metrics."""
    try:
        if not ml_predictions:
            fig = go.Figure()
            fig.add_annotation(
                text="No ML predictions available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=16)
            )
            fig.update_layout(title="📈 ML Forecasts", height=300)
            return fig
        
        # Create subplots for different metrics
        metric_names = list(ml_predictions.keys())
        n_metrics = len(metric_names)
        
        if n_metrics == 0:
            return create_continuous_learning_status_chart({})
        
        # Calculate subplot layout
        cols = min(2, n_metrics)
        rows = (n_metrics + cols - 1) // cols
        
        subplot_titles = [name.split(".")[-1].replace("_", " ").title() for name in metric_names]
        
        fig = make_subplots(
            rows=rows, cols=cols,
            subplot_titles=subplot_titles,
            vertical_spacing=0.15,
            horizontal_spacing=0.1
        )
        
        colors = COLORBLIND_PALETTE
        
        for i, (metric_name, prediction_data) in enumerate(ml_predictions.items()):
            row = (i // cols) + 1
            col = (i % cols) + 1
            
            forecast = prediction_data.get("forecast", {})
            if not forecast:
                continue
                
            dates = forecast.get("dates", [])
            values = forecast.get("values", [])
            confidence_intervals = forecast.get("confidence_intervals", [])
            
            if not dates or not values:
                continue
            
            # Convert dates
            try:
                x_dates = [datetime.strptime(d, "%Y-%m-%d") for d in dates]
            except:
                x_dates = dates
            
            # Main forecast line
            fig.add_trace(
                go.Scatter(
                    x=x_dates,
                    y=values,
                    mode='lines+markers',
                    name=f"{metric_name.split('.')[-1]} Forecast",
                    line=dict(color=colors[i % len(colors)], width=3),
                    showlegend=(row == 1 and col == 1)  # Only show legend for first chart
                ),
                row=row, col=col
            )
            
            # Confidence interval
            if confidence_intervals and len(confidence_intervals) == len(values):
                upper_bound = [ci[1] if isinstance(ci, list) and len(ci) >= 2 else ci for ci in confidence_intervals]
                lower_bound = [ci[0] if isinstance(ci, list) and len(ci) >= 2 else ci for ci in confidence_intervals]
                
                fig.add_trace(
                    go.Scatter(
                        x=x_dates + x_dates[::-1],
                        y=upper_bound + lower_bound[::-1],
                        fill='toself',
                        fillcolor=f'rgba({",".join(map(str, [int(colors[i % len(colors)][1:3], 16), int(colors[i % len(colors)][3:5], 16), int(colors[i % len(colors)][5:7], 16)]))}, 0.2)',
                        line=dict(color='rgba(255,255,255,0)'),
                        name='Confidence Interval',
                        showlegend=False
                    ),
                    row=row, col=col
                )
        
        fig.update_layout(
            title="📈 ML Forecast Dashboard - Continuous Learning Predictions",
            height=400 * rows,
            paper_bgcolor=get_bgcolor(),
            plot_bgcolor=get_bgcolor()
        )
        
        return fig
        
    except Exception as e:
        logger.error(f"Failed to create ML forecast comparison chart: {e}")
        fig = go.Figure()
        fig.add_annotation(
            text=f"Error creating forecast chart: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="red")
        )
        fig.update_layout(title="📈 ML Forecasts - Error", height=300)
        return fig

def create_line_chart(df: pd.DataFrame, x_col: str, y_col: str, title: str, color: str = "steelblue") -> go.Figure:
    """Create a basic line chart."""
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=df[x_col],
        y=df[y_col],
        mode='lines+markers',
        line=dict(color=color, width=3),
        marker=dict(size=6),
        name=y_col,
        hovertemplate='<b>' + x_col + '</b>: %{x}<br><b>' + y_col + '</b>: %{y}<extra></extra>'
    ))
    
    fig.update_layout(
        title=title,
        xaxis_title=x_col,
        yaxis_title=y_col,
        showlegend=False,
        height=400,
        plot_bgcolor=get_bgcolor(),
        paper_bgcolor=get_bgcolor()
    )
    
    return fig

def create_bar_chart(df: pd.DataFrame, x_col: str, y_col: str, title: str, color: str = "steelblue") -> go.Figure:
    """Create a basic bar chart."""
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        x=df[x_col],
        y=df[y_col],
        marker_color=color,
        name=y_col,
        hovertemplate='<b>' + x_col + '</b>: %{x}<br><b>' + y_col + '</b>: %{y}<extra></extra>'
    ))
    
    fig.update_layout(
        title=title,
        xaxis_title=x_col,
        yaxis_title=y_col,
        showlegend=False,
        height=400,
        plot_bgcolor=get_bgcolor(),
        paper_bgcolor=get_bgcolor()
    )
    
    return fig

def create_pie_chart(df: pd.DataFrame, values_col: str, names_col: str, title: str) -> go.Figure:
    """Create a basic pie chart."""
    fig = go.Figure()
    
    fig.add_trace(go.Pie(
        labels=df[names_col],
        values=df[values_col],
        hole=0.3,
        hovertemplate='<b>%{label}</b><br>Count: %{value}<br>Percentage: %{percent}<extra></extra>'
    ))
    
    fig.update_layout(
        title=title,
        height=400,
        plot_bgcolor=get_bgcolor(),
        paper_bgcolor=get_bgcolor()
    )
    
    return fig

def get_fgcolor():
    return "#fff" if DARK_MODE else "#2c3e50"

def downsample_time_series(dates, values, max_points=200):
    """Downsample time series for performance if too many points."""
    if len(dates) <= max_points:
        return dates, values
    
    idx = np.linspace(0, len(dates) - 1, max_points).astype(int)
    return [dates[i] for i in idx], [values[i] for i in idx]

def create_error_chart(error_message: str, alt_text: str = None) -> go.Figure:
    """Create error chart when visualization fails, with alt text for accessibility."""
    fig = go.Figure()
    fig.add_annotation(
        x=0.5, y=0.5,
        text=f"⚠️ {error_message}",
        showarrow=False,
        font=dict(size=16, color="red"),
        xref="paper", yref="paper"
    )
    
    fig.update_layout(
        title="Visualization Error",
        height=400,
        paper_bgcolor=get_bgcolor(),
        plot_bgcolor=get_bgcolor(),
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=False, showticklabels=False, zeroline=False)
    )
    
    # Alt text for screen readers
    fig["layout"]["meta"] = {"alt": alt_text or error_message}
    return fig

def extract_nested_metric(metrics: Dict, metric_path: str) -> Optional[float]:
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
        logger.debug("Failed to extract nested metric for path: %s", metric_path)
        return None

def get_performance_color(value: float, metric_type: str) -> str:
    """Get color based on performance value and metric type."""
    if metric_type == 'lead_time':
        if value <= 24:
            return "#2ca02c"
        elif value <= 168:
            return "#ff7f0e"
        else:
            return "#d62728"
    elif metric_type == 'deploy_freq':
        if value >= 10:
            return "#2ca02c"
        elif value >= 3:
            return "#ff7f0e"
        else:
            return "#d62728"
    elif metric_type == 'failure_rate':
        if value <= 5:
            return "#2ca02c"
        elif value <= 15:
            return "#ff7f0e"
        else:
            return "#d62728"
    elif metric_type == 'mttr':
        if value <= 1:
            return "#2ca02c"
        elif value <= 24:
            return "#ff7f0e"
        else:
            return "#d62728"
    else:
        return "#0072B2"

def get_wlb_color(score: float) -> str:
    """Get color for work-life balance score."""
    if score >= 80:
        return "#2ca02c"
    elif score >= 60:
        return "#ff7f0e"
    else:
        return "#d62728"

def create_forecast_chart(historical: List[Dict], forecast: Dict, metric_name: str, title: str) -> go.Figure:
    """Create time series forecast chart with confidence intervals and downsampling."""
    try:
        fig = go.Figure()
        
        # Process historical data
        if historical:
            hist_dates = []
            hist_values = []
            
            for entry in sorted(historical, key=lambda x: x.get('timestamp', x.get('metric_timestamp', x.get('date', '')))):
                try:
                    # Try different timestamp field names
                    timestamp_field = entry.get('timestamp') or entry.get('metric_timestamp') or entry.get('date')
                    if not timestamp_field:
                        continue
                        
                    date = parse_timestamp(timestamp_field) if isinstance(timestamp_field, str) else timestamp_field
                    
                    # Try different metrics field names
                    metrics_data = entry.get('metrics', entry.get('metrics_data', {}))
                    value = extract_nested_metric(metrics_data, metric_name)
                    
                    # If nested extraction fails, try direct field access
                    if value is None:
                        value = entry.get(metric_name.split('.')[-1])  # Get last part of nested path
                        
                    if value is not None:
                        hist_dates.append(date)
                        hist_values.append(value)
                except Exception as e:
                    logger.debug(f"Failed to process historical entry: {e}")
                    continue
            
            # Downsample if needed
            hist_dates, hist_values = downsample_time_series(hist_dates, hist_values)
            
            # Add historical data
            if hist_dates and hist_values:
                fig.add_trace(go.Scatter(
                    x=hist_dates,
                    y=hist_values,
                    mode='lines+markers',
                    name='Historical Data',
                    line=dict(color='#1f77b4', width=2),
                    marker=dict(size=6)
                ))
        
        # Add forecast data
        if forecast and 'dates' in forecast and 'values' in forecast:
            forecast_dates = [parse_timestamp(d) if isinstance(d, str) else d for d in forecast['dates']]
            forecast_dates, forecast_values = downsample_time_series(forecast_dates, forecast['values'])
            
            fig.add_trace(go.Scatter(
                x=forecast_dates,
                y=forecast_values,
                mode='lines+markers',
                name='Forecast',
                line=dict(color='#ff7f0e', width=2, dash='dash'),
                marker=dict(size=6)
            ))
            
            # Add confidence intervals if available
            if 'confidence_intervals' in forecast:
                conf_intervals = forecast['confidence_intervals']
                if len(conf_intervals) == len(forecast_dates):
                    upper_bound = [ci[1] if isinstance(ci, list) and len(ci) > 1 else ci for ci in conf_intervals]
                    lower_bound = [ci[0] if isinstance(ci, list) and len(ci) > 1 else ci for ci in conf_intervals]
                    
                    fig.add_trace(go.Scatter(
                        x=forecast_dates + forecast_dates[::-1],
                        y=upper_bound + lower_bound[::-1],
                        fill='toself',
                        fillcolor='rgba(255, 127, 14, 0.2)',
                        line=dict(color='rgba(255,255,255,0)'),
                        name='Confidence Interval',
                        showlegend=True
                    ))
        
        # Add current time indicator
        current_time = datetime.now()
        fig.add_vline(
            x=current_time,
            line_dash="solid",
            line_color="red",
            annotation_text="Now",
            annotation_position="top left"
        )
        
        fig.update_layout(
            title=dict(text=title, x=0.5, font=dict(size=16, color=get_fgcolor())),
            xaxis_title="Date",
            yaxis_title=metric_name.replace('_', ' ').title(),
            hovermode='x unified',
            height=400,
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            paper_bgcolor=get_bgcolor(),
            plot_bgcolor=get_bgcolor()
        )
        
        return fig
    except Exception as e:
        logger.error(f"Error creating forecast chart: {e}")
        return create_error_chart("Failed to create forecast chart", alt_text="Forecast chart error")

def create_radar_chart(metrics: Dict[str, Any], title: str = "Performance Radar", benchmark_level: str = "elite") -> go.Figure:
    """Create enhanced performance radar chart with benchmarks"""
    try:
        # Extract metrics with defaults
        current_metrics = {
            'Lead Time (hrs)': min(metrics.get('lead_time_hours', 0), 200),  # Cap for visualization
            'Deploy Freq/Week': min(metrics.get('deployment_frequency', 0), 15),
            'Success Rate %': 100 - min(metrics.get('change_failure_rate', 0), 100),
            'Review Coverage %': min(metrics.get('review_coverage_percentage', 0), 100),
            'Commit Streak': min(metrics.get('productivity_patterns', {}).get('max_commit_streak', 0), 30),
            'Collaboration': min(metrics.get('collaboration', {}).get('unique_reviewers', 0), 10)
        }
        
        # Benchmark values (normalized to 0-100 scale)
        benchmark_data = {
            'elite': [90, 85, 95, 95, 80, 85],  # Normalized benchmark values
            'high': [70, 70, 85, 85, 65, 70],
            'medium': [50, 50, 70, 70, 50, 55]
        }
        
        # Normalize current metrics to 0-100 scale
        normalized_current = []
        for key, value in current_metrics.items():
            if 'Lead Time' in key:
                # Lower is better for lead time - invert scale
                normalized_current.append(max(0, 100 - (value / 5)))  # 5 hours = 80 points
            elif 'Deploy Freq' in key:
                normalized_current.append(min(100, value * 10))  # 10/week = 100 points
            elif '%' in key:
                normalized_current.append(value)  # Already percentage
            elif 'Streak' in key:
                normalized_current.append(min(100, value * 3.33))  # 30 days = 100 points
            else:
                normalized_current.append(min(100, value * 10))  # Scale to 100
        
        categories = list(current_metrics.keys())
        fig = go.Figure()
        
        # Add benchmark
        if benchmark_level in benchmark_data:
            fig.add_trace(go.Scatterpolar(
                r=benchmark_data[benchmark_level],
                theta=categories,
                fill='toself',
                name=f'{benchmark_level.title()} Benchmark',
                fillcolor='rgba(255, 127, 14, 0.2)',
                line=dict(color='orange', width=2, dash='dash')
            ))
        
        # Add current performance
        fig.add_trace(go.Scatterpolar(
            r=normalized_current,
            theta=categories,
            fill='toself',
            name='Your Performance',
            fillcolor='rgba(31, 119, 180, 0.3)',
            line=dict(color='#1f77b4', width=3)
        ))
        
        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 100],
                    ticksuffix='',
                    tickmode='linear',
                    tick0=0,
                    dtick=20
                ),
                angularaxis=dict(
                    tickfont=dict(size=12)
                )
            ),
            title=dict(
                text=title,
                x=0.5,
                font=dict(size=18, color='#2c3e50')
            ),
            height=500,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            paper_bgcolor='white',
            plot_bgcolor='white'
        )
        
        return fig
    except Exception as e:
        logger.error(f"Error creating radar chart: {e}")
        return create_error_chart("Failed to create radar chart")

def create_commit_trend_chart(metrics: Dict[str, Any]) -> Optional[go.Figure]:
    """Create commit activity trend visualization with moving average"""
    try:
        if 'weekly_commit_frequency' not in metrics:
            return None
        
        weekly_data = metrics['weekly_commit_frequency']
        if not weekly_data:
            return None
        
        # Sort by week
        sorted_weeks = sorted(weekly_data.keys())
        commits = [weekly_data[week] for week in sorted_weeks]
        
        # Calculate moving average
        window_size = min(4, len(commits))
        if window_size > 1:
            moving_avg = pd.Series(commits).rolling(window=window_size, min_periods=1).mean().tolist()
        else:
            moving_avg = commits
        
        fig = go.Figure()
        
        # Add bar chart for commits
        fig.add_trace(go.Bar(
            x=sorted_weeks,
            y=commits,
            name='Weekly Commits',
            marker_color='#1f77b4',
            opacity=0.7
        ))
        
        # Add trend line
        fig.add_trace(go.Scatter(
            x=sorted_weeks,
            y=moving_avg,
            mode='lines',
            name='Trend (4-week avg)',
            line=dict(color='#ff7f0e', width=3),
            yaxis='y2'
        ))
        
        fig.update_layout(
            title='Commit Activity Trend',
            xaxis_title='Week',
            yaxis_title='Commits',
            height=400,
            showlegend=True,
            yaxis2=dict(overlaying='y', side='right', showgrid=False),
            paper_bgcolor='white',
            plot_bgcolor='white'
        )
        
        return fig
    except Exception as e:
        logger.error(f"Error creating commit trend chart: {e}")
        return None

def create_activity_heatmap(metrics: Dict[str, Any]) -> Optional[go.Figure]:
    """Create weekly activity heatmap"""
    try:
        productivity = metrics.get('productivity_patterns', {})
        commits_by_day = productivity.get('commits_by_day', {})
        commits_by_hour = productivity.get('commits_by_hour', {})
        
        if not commits_by_day or not commits_by_hour:
            return None
        
        # Create 7x24 matrix for heatmap
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        hours = [f"{h:02d}:00" for h in range(24)]
        
        # Initialize matrix
        heatmap_data = np.zeros((7, 24))
        
        # Fill matrix with actual data
        day_mapping = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}  # Assuming 0=Monday
        
        total_commits = sum(commits_by_day.values())
        if total_commits == 0:
            return None
        
        # Distribute commits across hours (simplified approach)
        for day_idx, commits in commits_by_day.items():
            if day_idx in day_mapping:
                row = day_mapping[day_idx]
                # Distribute commits across hours based on hour distribution
                for hour, hour_commits in commits_by_hour.items():
                    if 0 <= hour < 24:
                        # Weight by day activity
                        heatmap_data[row][hour] = (commits / total_commits) * hour_commits
        
        fig = go.Figure(data=go.Heatmap(
            z=heatmap_data,
            x=hours,
            y=days,
            colorscale='Blues',
            showscale=True,
            colorbar=dict(title="Activity Level")
        ))
        
        fig.update_layout(
            title='Weekly Activity Heatmap',
            xaxis_title='Hour of Day',
            yaxis_title='Day of Week',
            height=400,
            paper_bgcolor='white',
            plot_bgcolor='white'
        )
        
        return fig
    except Exception as e:
        logger.error(f"Error creating activity heatmap: {e}")
        return None

def create_performance_timeline_chart(historical_data: List[Dict]) -> go.Figure:
    """Create performance grade timeline chart"""
    try:
        if not historical_data:
            return create_error_chart("No historical data available")
        
        dates = []
        grades = []
        percentages = []
        
        for entry in sorted(historical_data, key=lambda x: x.get('metric_timestamp', '')):
            try:
                date = parse_timestamp(entry['metric_timestamp'])
                perf_grade = entry.get('metrics_data', {}).get('performance_grade', {})
                if perf_grade:
                    dates.append(date)
                    grades.append(perf_grade.get('overall_grade', 'N/A'))
                    percentages.append(perf_grade.get('percentage', 0))
            except Exception:
                continue
        
        if not dates:
            return create_error_chart("No performance data found")
        
        fig = go.Figure()
        
        # Add percentage line
        fig.add_trace(go.Scatter(
            x=dates,
            y=percentages,
            mode='lines+markers+text',
            name='Performance Score',
            text=grades,
            textposition='top center',
            line=dict(color='#1f77b4', width=3),
            marker=dict(size=8)
        ))
        
        # Add grade bands
        fig.add_hrect(y0=90, y1=100, fillcolor="rgba(46, 160, 44, 0.2)",
                     annotation_text="A+", annotation_position="left")
        fig.add_hrect(y0=80, y1=90, fillcolor="rgba(255, 127, 14, 0.2)",
                     annotation_text="B+", annotation_position="left")
        fig.add_hrect(y0=70, y1=80, fillcolor="rgba(214, 39, 40, 0.2)",
                     annotation_text="C+", annotation_position="left")
        
        fig.update_layout(
            title='Performance Grade Timeline',
            xaxis_title='Date',
            yaxis_title='Performance Score (%)',
            yaxis_range=[0, 100],
            height=400,
            hovermode='x unified',
            paper_bgcolor='white',
            plot_bgcolor='white'
        )
        
        return fig
    except Exception as e:
        logger.error(f"Error creating performance timeline: {e}")
        return create_error_chart("Failed to create performance timeline")

def create_dora_metrics_dashboard(metrics: Dict[str, Any]) -> go.Figure:
    """Create comprehensive DORA metrics dashboard"""
    try:
        dora = metrics.get('dora', {})
        
        # Create a simple bar chart instead of complex subplots with indicators
        dora_metrics = [
            'Lead Time (hrs)',
            'Deploy Freq (/week)',
            'Success Rate (%)',
            'Recovery Time (hrs)'
        ]
        
        values = [
            dora.get('lead_time', {}).get('total_lead_time_hours', 0),
            dora.get('deployment_frequency', {}).get('per_week', 0),
            100 - dora.get('change_failure_rate', {}).get('percentage', 0),
            dora.get('mean_time_to_recovery', {}).get('hours', 0)
        ]
        
        # Create color scale based on performance
        colors = []
        for i, value in enumerate(values):
            if i == 0:  # Lead time - lower is better
                color = '#2E8B57' if value < 24 else '#FFD700' if value < 168 else '#DC143C'
            elif i == 1:  # Deploy frequency - higher is better
                color = '#2E8B57' if value > 5 else '#FFD700' if value > 1 else '#DC143C'
            elif i == 2:  # Success rate - higher is better
                color = '#2E8B57' if value > 90 else '#FFD700' if value > 70 else '#DC143C'
            else:  # Recovery time - lower is better
                color = '#2E8B57' if value < 24 else '#FFD700' if value < 168 else '#DC143C'
            colors.append(color)
        
        fig = go.Figure(data=[
            go.Bar(
                x=dora_metrics,
                y=values,
                marker_color=colors,
                text=[f'{v:.1f}' for v in values],
                textposition='auto',
            )
        ])
        
        fig.update_layout(
            title="DORA Metrics Overview",
            xaxis_title="Metrics",
            yaxis_title="Values",
            height=400,
            showlegend=False,
            plot_bgcolor=get_bgcolor(),
            paper_bgcolor=get_bgcolor(),
            font_color=get_fgcolor()
        )
        
        return fig
    except Exception as e:
        logger.error(f"Error creating DORA dashboard: {e}")
        return create_error_chart(f"Failed to create DORA dashboard: {str(e)}")

def create_anomaly_detection_chart(anomalies: Dict[str, Any], historical_data: List[Dict], metric_name: str) -> go.Figure:
    """Create anomaly detection visualization"""
    try:
        fig = go.Figure()
        
        # Plot historical data
        dates = []
        values = []
        for entry in sorted(historical_data, key=lambda x: x.get('timestamp', '')):
            try:
                date = parse_timestamp(entry['timestamp'])
                value = extract_nested_metric(entry.get('metrics', {}), metric_name)
                if value is not None:
                    dates.append(date)
                    values.append(value)
            except Exception:
                continue
        
        # Add normal data points
        fig.add_trace(go.Scatter(
            x=dates,
            y=values,
            mode='lines+markers',
            name='Normal Data',
            line=dict(color='#1f77b4', width=2),
            marker=dict(size=6)
        ))
        
        # Highlight anomalies
        anomaly_data = anomalies.get('anomalies', [])
        if anomaly_data:
            anomaly_dates = []
            anomaly_values = []
            anomaly_texts = []
            
            for anomaly in anomaly_data:
                try:
                    anom_date = parse_timestamp(anomaly['timestamp'])
                    anomaly_dates.append(anom_date)
                    anomaly_values.append(anomaly['value'])
                    anomaly_texts.append(f"Method: {anomaly['method']}<br>Severity: {anomaly.get('severity', 'N/A'):.2f}")
                except Exception:
                    continue
            
            if anomaly_dates:
                fig.add_trace(go.Scatter(
                    x=anomaly_dates,
                    y=anomaly_values,
                    mode='markers',
                    name='Anomalies',
                    marker=dict(color='red', size=12, symbol='x'),
                    text=anomaly_texts,
                    hovertemplate='<b>Anomaly Detected</b><br>%{text}<extra></extra>'
                ))
        
        fig.update_layout(
            title=f'Anomaly Detection - {metric_name.replace("_", " ").title()}',
            xaxis_title='Date',
            yaxis_title=metric_name.replace('_', ' ').title(),
            height=400,
            hovermode='x unified',
            paper_bgcolor='white',
            plot_bgcolor='white'
        )
        
        return fig
    except Exception as e:
        logger.error(f"Error creating anomaly chart: {e}")
        return create_error_chart("Failed to create anomaly detection chart")

def create_collaboration_network(metrics: Dict[str, Any]) -> go.Figure:
    """Create collaboration network visualization"""
    try:
        collaboration = metrics.get('collaboration', {})
        top_reviewers = collaboration.get('top_reviewers', {})
        
        if not top_reviewers:
            return create_error_chart("No collaboration data available")
        
        # Create network-style visualization
        reviewers = list(top_reviewers.keys())[:10]  # Top 10 reviewers
        review_counts = [top_reviewers[r] for r in reviewers]
        
        # Create bubble chart to represent collaboration
        fig = go.Figure(data=go.Scatter(
            x=list(range(len(reviewers))),
            y=[1] * len(reviewers),  # All on same horizontal line
            mode='markers+text',
            marker=dict(
                size=[count * 10 for count in review_counts],  # Size based on review count
                color=review_counts,
                colorscale='Viridis',
                showscale=True,
                colorbar=dict(title="Review Count")
            ),
            text=reviewers,
            textposition='middle center',
            hovertemplate='<b>%{text}</b><br>Reviews: %{marker.color}<extra></extra>'
        ))
        
        fig.update_layout(
            title='Top Collaborators',
            xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
            yaxis=dict(showgrid=False, showticklabels=False, zeroline=False, range=[0.5, 1.5]),
            height=300,
            paper_bgcolor='white',
            plot_bgcolor='white'
        )
        
        return fig
    except Exception as e:
        logger.error(f"Error creating collaboration network: {e}")
        return create_error_chart("Failed to create collaboration network")

def create_work_life_balance_chart(metrics: Dict[str, Any]) -> go.Figure:
    """Create work-life balance visualization"""
    try:
        productivity = metrics.get('productivity_patterns', {})
        weekend_pct = productivity.get('weekend_work_percentage', 0)
        late_night_pct = productivity.get('late_night_work_percentage', 0)
        wlb_score = productivity.get('work_life_balance_score') or metrics.get('work_life_balance_score', 0)
        
        # Create gauge chart for work-life balance score
        fig = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=wlb_score,
            domain={'x': [0, 0.5], 'y': [0.5, 1]},
            title={'text': "Work-Life Balance Score"},
            delta={'reference': 80, 'increasing': {'color': "green"}, 'decreasing': {'color': "red"}},
            gauge={
                'axis': {'range': [None, 100]},
                'bar': {'color': get_wlb_color(wlb_score)},
                'steps': [
                    {'range': [0, 40], 'color': "lightcoral"},
                    {'range': [40, 70], 'color': "yellow"},
                    {'range': [70, 100], 'color': "lightgreen"}
                ],
                'threshold': {
                    'line': {'color': "red", 'width': 4},
                    'thickness': 0.75,
                    'value': 60
                }
            }
        ))
        
        # Add annotations for weekend and late night work
        fig.add_annotation(
            x=0.5, y=0.15,
            text=f"Weekend Work: {weekend_pct:.1f}%<br>Late Night Work: {late_night_pct:.1f}%",
            showarrow=False,
            font=dict(size=12),
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="gray",
            borderwidth=1
        )
        
        fig.update_layout(
            height=400,
            paper_bgcolor='white'
        )
        
        return fig
    except Exception as e:
        logger.error(f"Error creating work-life balance chart: {e}")
        return create_error_chart("Failed to create work-life balance chart")
