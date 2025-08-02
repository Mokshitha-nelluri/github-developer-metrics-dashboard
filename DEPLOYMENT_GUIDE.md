# GitHub Metrics Dashboard - Deployment Guide

## 🚀 Deployment Options

### 1. **Streamlit Community Cloud** (Recommended - Free & Easy)

#### Prerequisites:
- GitHub repository (your code needs to be in a GitHub repo)
- Streamlit Community Cloud account (free)

#### Steps:
1. **Push your code to GitHub:**
   ```bash
   git init
   git add .
   git commit -m "Initial commit - GitHub Metrics Dashboard"
   git branch -M main
   git remote add origin https://github.com/yourusername/github-metrics.git
   git push -u origin main
   ```

2. **Deploy to Streamlit Cloud:**
   - Go to [share.streamlit.io](https://share.streamlit.io)
   - Click "New app"
   - Connect your GitHub repository
   - Set main file path: `frontend/dashboard.py`
   - Add your environment variables in "Advanced settings"

3. **Environment Variables for Streamlit Cloud:**
   ```toml
   AWS_DEPLOYMENT = "true"
   DATABASE_URL = "postgresql://user:pass@host:5432/db"
   GEMINI_API_KEY = "your_gemini_key"
   GITHUB_TOKEN = "your_github_token"
   GITHUB_CLIENT_ID = "your_client_id"
   GITHUB_CLIENT_SECRET = "your_client_secret"
   OAUTH_REDIRECT_URI = "https://your-app.streamlit.app"
   ```

#### ✅ Pros:
- Free hosting
- Automatic SSL/HTTPS
- Easy deployment and updates
- Built for Streamlit apps

#### ❌ Cons:
- Limited to 1GB RAM
- Community tier has resource limits
- Streamlit branding

---

### 2. **AWS ECS with Docker** (Professional)

#### Prerequisites:
- AWS Account
- Docker installed locally
- AWS CLI configured

#### Files Created:
- `Dockerfile` - Container definition
- `docker-compose.yml` - Local testing
- `deploy-aws.yml` - GitHub Actions deployment

#### Steps:
1. **Build and test locally:**
   ```bash
   docker-compose up --build
   ```

2. **Deploy to AWS ECS:**
   - Push to GitHub
   - GitHub Actions will automatically deploy
   - Or use AWS CLI manually

#### ✅ Pros:
- Professional deployment
- Scalable and reliable
- Full control over environment
- Custom domain support

#### ❌ Cons:
- AWS costs (~$20-50/month)
- More complex setup
- Requires AWS knowledge

---

### 3. **Railway** (Alternative - Simple & Affordable)

#### Steps:
1. Connect GitHub repo to Railway
2. Set environment variables
3. Deploy automatically

#### ✅ Pros:
- $5/month starter plan
- Very easy deployment
- Good for small projects

---

## 📁 Project Structure (Deployment Ready)

```
github_metrics/
├── app.py                    # 🆕 Unified launcher
├── requirements.txt          # Python dependencies
├── Dockerfile               # 🆕 Container definition
├── docker-compose.yml       # 🆕 Local testing
├── .dockerignore           # 🆕 Docker ignore rules
├── deploy-aws.yml          # 🆕 GitHub Actions deployment
├── frontend/
│   ├── dashboard.py        # Main Streamlit app
│   └── visualization.py   # Charts and graphs
├── backend/
│   ├── aws_data_store.py   # Database layer
│   ├── github_api.py       # GitHub integration
│   ├── metrics_calculator.py
│   ├── ml_analyzer.py
│   └── summary_bot.py
└── config.py               # Configuration

# 🗑️ Deprecated Files (can be removed):
├── start.py                # Replaced by app.py
├── start_dashboard.py      # Replaced by app.py
├── main.py                 # Empty file
└── *.bat files             # Windows batch files
```

## 🏃‍♂️ Quick Start Commands

### Local Development:
```bash
# Production mode (uses AWS RDS)
python app.py

# Development mode (uses .env file)
python app.py --dev

# Custom port
python app.py --port 8502
```

### Docker:
```bash
# Build and run locally
docker-compose up --build

# Production build
docker build -t github-metrics .
docker run -p 8501:8501 github-metrics
```

## 🔧 Configuration

### Production (AWS):
- Environment variables are hardcoded in `app.py`
- Uses AWS RDS PostgreSQL database
- GitHub OAuth for authentication

### Development:
- Requires `.env` file
- Can use local Supabase or AWS RDS
- Additional auth server for local OAuth

## 🎯 Recommended Deployment Path

1. **Start with Streamlit Cloud** - Free and fast setup
2. **Upgrade to AWS ECS** - When you need more resources/control
3. **Consider Railway** - Good middle ground option

Choose based on your needs:
- **Learning/Demo**: Streamlit Community Cloud
- **Production App**: AWS ECS
- **Small Business**: Railway

## 📞 Need Help?

Each deployment option has detailed setup instructions below. Choose your preferred method and follow the specific guide!
