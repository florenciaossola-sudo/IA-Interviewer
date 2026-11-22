import { createRoot } from "react-dom/client";

import "../styles.css";
import { App } from "../src/AdminApp";

createRoot(document.getElementById("root") as HTMLElement).render(<App />);
