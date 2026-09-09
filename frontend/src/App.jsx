import { Route, Routes } from "react-router-dom";
import Navbar from "./components/Navbar";
import Dashboard from "./pages/Dashboard";
import Games from "./pages/Games";
import Markets from "./pages/Markets";
import Props from "./pages/Props";

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <Navbar />
      <div className="flex-1 max-w-7xl mx-auto w-full">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/games" element={<Games />} />
          <Route path="/props" element={<Props />} />
          <Route path="/markets" element={<Markets />} />
        </Routes>
      </div>
    </div>
  );
}
