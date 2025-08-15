import { Inter } from "next/font/google";

const inter = Inter({ subsets: ["latin"] });

export default function Home({ children }: { children: React.ReactNode; }) {
  return (
    <html lang="en">
      <body className={`${inter.className}`}>
        {children}
      </body>
    </html>
  );
}

export async function getServerSideProps() {
  return {
    redirect: {
      destination: "/dashboard",
      permanent: false,
    },
  };
}