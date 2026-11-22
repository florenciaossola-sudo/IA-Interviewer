import { createRoot } from "react-dom/client";

import "../styles.css";
import { App } from "../src/ReviewerApp";

createRoot(document.getElementById("root") as HTMLElement).render(<App />);
