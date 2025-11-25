# 🚨 AIML-CyberDefense-System  
### **AI + Machine Learning based Intelligent Cyber Defense System**  
![Python](https://img.shields.io/badge/Python-3.11-blue.svg)
![Flask](https://img.shields.io/badge/Flask-Backend-black)
![React](https://img.shields.io/badge/React-Frontend-61dafb.svg)
![Vite](https://img.shields.io/badge/Vite-Bundler-purple)
![Socket.IO](https://img.shields.io/badge/Socket.IO-Realtime-333333.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)

---

## 📌 **1. Project Overview**
**AIML-CyberDefense-System** is a full-stack AI-powered cyber defense platform that detects **network intrusions (DDoS, Botnet, SYN Floods)** and **human vs bot behavior** using:

- **ML models on Network Flow Data**  
- **Behavioral Biometrics via Mouse Dynamics**  
- **Real-Time Event Streaming (Socket.IO)**  
- **Automated Flow Collector**  
- **Rate-Limit + Automation Detection Engine**

This system demonstrates modern cybersecurity research principles by integrating **machine learning, real-time data processing, human-behavior analysis, and full-stack engineering**.

---

## 🧠 **2. Core Features**

### 🔹 **A. Network Intrusion Detection (Flow-Based ML)**
- Random Forest
- XGBoost Booster Model
- Preprocessing pipeline
- Flow sliding-window engine
- Real-time threat alerts via SocketIO

### 🔹 **B. Mouse Dynamics Behavioral Detection**
Detect whether the visitor is:
- 🤖 **Bot**
- 🧑 **Human**
Using:
- RF classifier on 20 handcrafted features  
- LSTM deep-learning model  
- Ensemble prediction + hysteresis windowing  

### 🔹 **C. Real-Time Dashboard**
- Live flow chart  
- Alerts panel  
- Model confidence values  
- Mouse trajectory visualization  
- System health monitor  

### 🔹 **D. Security System**
- Rate limiting  
- IP window blocking  
- Automation detection (Selenium, Puppeteer, Playwright)  
- JWT Authentication (Access + Refresh tokens)  
- Password hashing with bcrypt  
- Refresh token revocation  

### 🔹 **E. Frontend (React + Vite)**
- Modern UI  
- Auth pages  
- Dashboard  
- Live streaming visualizer  
- Notifications + toast alerts  

### 🔹 **F. Backend (Flask + Socket.IO)**
- Robust REST APIs  
- Auto-injected event collector scripts  
- Database models  
- Logging & exception handling  
- Modular blueprint routing  

---

## 🏗 **3. System Architecture**

```
                    ┌───────────────────────┐
                    │      FRONTEND (UI)     │
                    │ React + Vite + Charts │
                    └─────────────┬─────────┘
                                  │ HTTPS/WS
                           Socket.IO + REST API
                                  │
                    ┌─────────────┴─────────────┐
                    │        BACKEND API         │
                    │ Flask + Socket.IO Server  │
                    ├─────────────┬─────────────┤
                    │Authentication│ML Prediction│
                    └───────┬─────┴──────┬──────┘
                            │             │
                   ┌────────┘   ┌────────┘
                   ▼            ▼
           ML Flow Models   Mouse Dynamics Engine
          (RF, XGB, Scaler) (RF, LSTM, Ensemble)
                   │            │
                   └──────┬─────┘
                          ▼
               Real-Time Alerts + Logging
                          │
                   SQL Database (MySQL)
```

---

## 🗂 **4. Folder Structure**

```
AIML-CyberDefense-System/
│
├── backend/
│   ├── app.py
│   ├── auth.py
│   ├── mouse_model.py
│   ├── db.py
│   ├── routes/
│   ├── static/
│   │   ├── flow_report.js
│   │   ├── index.html
│   │   └── blocked.html
│   ├── templates/
│   ├── models/
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   ├── vite.config.js
│   ├── package.json
│   └── dist/ (GitHub Pages build)
│
├── data/
│   ├── raw/
│   └── processed/
│
├── .env.example
├── Dockerfile
├── docker-compose.yml  (optional)
└── README.md
```

---

## 🔧 **5. Technology Stack**

### **Frontend**
- React 18  
- Vite  
- Socket.IO Client  
- Zustand  
- Chart.js  
- Custom Mouse Visualizer  

### **Backend**
- Python 3.11  
- Flask  
- Flask-SocketIO  
- SQLAlchemy  
- JWT  
- bcrypt  
- Limiter  
- Requests  
- Eventlet  

### **Machine Learning**
- Scikit-Learn  
- XGBoost  
- TensorFlow/Keras (LSTM model)  
- NumPy, Pandas  
- Joblib  

### **DevOps**
- Docker-ready  
- GitHub Pages deployment for frontend  
- GitHub Actions CI/CD (optional)

---

## 🧪 **6. ML Models Overview**

### **➡ Flow Models**
| Model | Purpose | File |
|-------|---------|-------|
| Random Forest | Baseline binary classifier | `rf_model.save` |
| XGBoost | Final booster | `xgb_model.json` |
| Scaler | Standardization | `scaler_used.save` |
| Label Encoder | Multiclass mapping | `label_encoder.save` |

### **➡ Mouse Dynamics Models**
| Model | Purpose | File |
|--------|----------|--------|
| RF | Feature-based classification | `mouse_rf.save` |
| LSTM | Sequential deep model | `mouse_lstm.h5` / `.keras` |
| Scaler | Normalization | `mouse_lstm_scaler.save` |
| Ensemble Meta | Weight tuning | `mouse_ensemble_meta.json` |

---

## 🧪 **7. Dataset Information**

### **Flow-Based ML Dataset**
- ISCX / CICIDS 2017/2018  
- Custom cleaned CSVs  
- Reduced features + label balancing  

### **Mouse Dynamics**
- **ISIT 2024 Bits & Bots dataset**  
- **Balabit refined dataset (scroll behavior)**  
- Custom preprocessing scripts  
- 20 handcrafted features (speed, acceleration, angles, pauses, curvature…)

---

## 🛠 **8. Installation & Setup**

### 1️⃣ Clone the repository
```bash
git clone https://github.com/Spyderzz/AIML-CyberDefense-System
cd AIML-CyberDefense-System
```

### 2️⃣ Backend Setup
```bash
cd backend
python -m venv venv
venv/Scripts/activate
pip install -r requirements.txt
```

### 3️⃣ Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

### 4️⃣ Environment Variables
Create file:

`.env` (NOT uploaded)

```
SECRET_KEY=
DATABASE_USER=
DATABASE_PASSWORD=
DATABASE_NAME=cyberdefense
FRONTEND_ORIGIN=http://localhost:3000
FLOWCOLLECTOR_TOKEN=
```

### Use `.env.example` as reference.

---

## 🚀 **9. Build Frontend for GitHub Pages**

```bash
cd frontend
npm run build
```

The output goes into:  
`frontend/dist/`

This is deployed automatically via GitHub Pages using workflow:

`.github/workflows/deploy.yml`

---

## 🐋 **10. Docker Deployment**

### **Build the container**
```bash
docker build -t aiml-cyberdefense .
```

### **Run**
```bash
docker run -p 5000:5000 aiml-cyberdefense
```

---

## ⚙ **11. Backend API Summary**

### **POST /api/predict_flow**
Predict intrusion using flow features.

### **POST /api/predict_mouse**
Predict human/bot from mouse events.

### **POST /api/collect_mouse**
Record + predict in real time.

### **POST /api/predict_combined**
Ensemble of flow + mouse.

### **Auth Endpoints**
`/auth/register`  
`/auth/login`  
`/auth/refresh`  
`/auth/logout`

---

## 🔐 **12. Security Features**
- bcrypt hashing  
- JWT-based auth  
- Rate limiting  
- IP-based sliding window  
- Auto block/unblock  
- Automation detection (Selenium, Puppeteer, Playwright)  
- CSRF-safe design  
- No sensitive data in GitHub (via .gitignore)

---

## 📦 **13. .gitignore (Key Entries)**

```
# Environment
.env
*.env

# Models
*.h5
*.keras
*.joblib
*.save
*.pkl

# Datasets
data/raw/*
data/processed/*

# Node
node_modules/
dist/

# Python
__pycache__/
*.pyc
```

---

## 📝 **14. License**
This project is licensed under the **MIT License**.  
You are free to use, modify, and distribute it with attribution.

---

## 🤝 **15. Contributing**
Pull requests and improvements are welcome.  
Feel free to open issues for:

- Bug reports  
- Feature requests  
- Model improvements  
- Optimization suggestions  

---

## ⭐ **16. Author**
**Atharva Rathore**  
B.Tech Student – AI/ML & Cyber Security  
GitHub: https://github.com/Spyderzz  
Project: **AIML-CyberDefense-System**

---

## 🎉 **17. Acknowledgements**
- ISIT 2024 Bits & Bots Dataset  
- CICIDS 2017 / 2018  
- Balabit Mouse Dynamics Dataset  
- Flask, React, Vite Teams  
- scikit-learn, XGBoost, TensorFlow  

---

# 🚀 **Feel free to star ⭐ the project if you like it!**
