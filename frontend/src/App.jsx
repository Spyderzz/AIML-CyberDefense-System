import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Index from "./pages/index";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import MouseTest from "./pages/MouseTest";
import ProtectedRoute from "./components/ProtectedRoute";
import useMouseDynamics from "./hooks/useMouseDynamics";

export default function App(){

    useMouseDynamics({intervalMs: 3000, batchLimit:800, enableSend: true});
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Index />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />

        <Route path="/dashboard" element={<ProtectedRoute><Dashboard/></ProtectedRoute>} />
        <Route path="/mouse_test" element={<ProtectedRoute><MouseTest/></ProtectedRoute>} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
