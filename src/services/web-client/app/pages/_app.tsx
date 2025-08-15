import "../styles/globals.css";
import type { AppProps } from "next/app";
import Navbar from "../ui/navbar/navbar";
import Sidebar from "../ui/sidebar/sidebar";

export default function App({ Component, pageProps }: AppProps) {
  return (
    <div className="flex h-fill">
        <div className='w-56 bg-[var(--bgSoft)] p-4 shadow-xl min-h-[100vh]'>
            <Sidebar/>
        </div>
        <div className="flex-4 p-4">
            <Navbar/>
            <Component {...pageProps} />
        </div>
    </div>
  );
}
