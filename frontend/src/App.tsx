
import { BrowserRouter } from "react-router-dom";
import AppRouter from "./app/routing/AppRouter";
import { AppProvider } from "./app/providers/AppProvider";
import { ThemeProvider } from "./theme/ThemeProvider";

export default function App() {
  // ThemeProvider sits inside AppProvider so the theme can follow the signed-in user.
  return (
    <BrowserRouter>
      <AppProvider>
        <ThemeProvider>
          <AppRouter />
        </ThemeProvider>
      </AppProvider>
    </BrowserRouter>
  );
}
