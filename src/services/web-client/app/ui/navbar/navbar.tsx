import { usePathname } from "next/navigation";
import { MdOutlineLightMode, MdOutlineNotifications, MdOutlineViewSidebar, MdSearch } from "react-icons/md";

const Navbar = () => {

    const pathname = usePathname();
    console.log(pathname);
    return (
        <div className="flex justify-between items-center p-4 bg-[var(--bgSoft)] rounded-lg shadow-xl">
            <div className="flex gap-3 text-[var(--textSoft)] font-bold capitalize items-center">
                <MdOutlineViewSidebar size={20} className="text-[var(--text)] my-auto rotate-y-180" />
                {pathname?.split("/").pop()}
            </div>
            <div className="flex gap-4 items-center">
                <div className="flex gap-3 items-center bg-[#2e374a] rounded-lg p-2">
                    <MdSearch/>
                    <input type="text" placeholder="Search..." />
                </div>
                <div className="flex gap-4">
                    <MdOutlineLightMode size={20}/>
                    <MdOutlineNotifications size={20}/>
                    {/* <MdOutlineViewSidebar size={20}/> */}
                </div>
            </div>
        </div>
    )
}

export default Navbar;