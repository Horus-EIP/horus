const Card = ({ title, number }: { title: string; number: number }) => {
    return (
        <div className="flex p-4 bg-[var(--bgSoft)] rounded-lg cursor-pointer w-full hover:bg-[#2e374a] shadow-xl">
            <div className="flex flex-col gap-4">
                <span className="text-[var(--textSoft)] text-xl">
                    {title}
                </span>
                <span className="text-[var(--text)] text-4xl font-semibold">
                    {number}
                </span>
            </div>
        </div>
    )
}

export default Card;